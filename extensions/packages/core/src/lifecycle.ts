/**
 * PropStein Live Sniper — Signal Lifecycle
 * ======================================
 * Owns the lifetime of signals across observations:
 *  - upsert on every observation change (odds change → immediate re-evaluation)
 *  - withdrawal when a market is removed, suspended, expires, or its drive ends
 *  - alert deduplication and oscillation guards (hysteresis + cooldown)
 *  - drive-end invalidation: EVERY signal tied to a drive becomes invalid,
 *    even if its old price remains visible on the page (spec critical test).
 */

import type {
  DriveContext,
  MarketChangeEvent,
  ModelEvaluation,
  NormalizedMarket,
  ObservedMarket,
  SignalEngineConfig,
  SignalSnapshot,
  SignalState,
} from "./market-types.ts";
import { evaluateSignal } from "./signal-engine.ts";
import { DEFAULT_SIGNAL_ENGINE_CONFIG } from "./signal-engine.ts";
import { normalizeObservedMarket } from "./market-normalizer.ts";

export interface LifecycleEvent {
  type: "signal-updated" | "alert-raised" | "alert-withdrawn" | "signal-removed";
  snapshot: SignalSnapshot;
  at: string;
}

export interface RegistryOptions {
  config?: SignalEngineConfig;
  /** Minimum time between repeated alerts for the same signal key. */
  alertCooldownMs?: number;
  /** Signals older than this with no re-observation are pruned. */
  maxSignalIdleMs?: number;
  now?: () => number;
}

interface RegistryEntry {
  snapshot: SignalSnapshot;
  lastAlertAt: number;
  lastWithdrawNotifiedAt: number;
}

export class SignalRegistry {
  private readonly signals = new Map<string, RegistryEntry>();
  private readonly listeners = new Set<(e: LifecycleEvent) => void>();
  private readonly config: SignalEngineConfig;
  private readonly alertCooldownMs: number;
  private readonly maxSignalIdleMs: number;
  private readonly now: () => number;

  constructor(opts: RegistryOptions = {}) {
    this.config = opts.config ?? DEFAULT_SIGNAL_ENGINE_CONFIG;
    this.alertCooldownMs = opts.alertCooldownMs ?? 30_000;
    this.maxSignalIdleMs = opts.maxSignalIdleMs ?? 120_000;
    this.now = opts.now ?? (() => Date.now());
  }

  onEvent(listener: (e: LifecycleEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(type: LifecycleEvent["type"], snapshot: SignalSnapshot): void {
    const event: LifecycleEvent = { type, snapshot, at: new Date(this.now()).toISOString() };
    for (const l of this.listeners) l(event);
  }

  /**
   * Process a new/updated observation for a signal key. Re-evaluates the
   * full state machine immediately — the displayed estimate must always
   * reflect the LATEST observed odds.
   */
  observe(
    signalKey: string,
    observed: ObservedMarket,
    opts: {
      normalized?: NormalizedMarket;
      model?: ModelEvaluation;
      match?: import("./market-types.ts").MatchResult;
      driveContext?: DriveContext;
      visible?: boolean;
    } = {},
  ): SignalSnapshot {
    const nowMs = this.now();
    const previous = this.signals.get(signalKey);
    const normalized = opts.normalized ?? normalizeObservedMarket(observed);
    const previousState: SignalState | undefined = previous?.snapshot.state;

    const snapshot = evaluateSignal({
      signalKey,
      observed,
      normalized,
      ...(opts.match !== undefined ? { match: opts.match } : {}),
      ...(opts.model !== undefined ? { model: opts.model } : {}),
      ...(opts.driveContext !== undefined ? { driveContext: opts.driveContext } : {}),
      ...(opts.visible !== undefined ? { visible: opts.visible } : {}),
      nowMs,
      config: this.config,
      ...(previousState !== undefined ? { previousState } : {}),
    });

    const entry: RegistryEntry = {
      snapshot,
      lastAlertAt: previous?.lastAlertAt ?? 0,
      lastWithdrawNotifiedAt: previous?.lastWithdrawNotifiedAt ?? 0,
    };
    this.signals.set(signalKey, entry);

    // Alert transitions with dedup + cooldown (oscillation guard).
    const becameAlertable = snapshot.state === "ALERTABLE" && previousState !== "ALERTABLE";
    if (becameAlertable) {
      if (nowMs - entry.lastAlertAt >= this.alertCooldownMs) {
        entry.lastAlertAt = nowMs;
        this.emit("alert-raised", snapshot);
      }
    } else if (previousState === "ALERTABLE" && snapshot.state !== "ALERTABLE") {
      // Alert withdrawal — the opportunity is no longer valid.
      if (nowMs - entry.lastWithdrawNotifiedAt >= this.alertCooldownMs) {
        entry.lastWithdrawNotifiedAt = nowMs;
        this.emit("alert-withdrawn", snapshot);
      }
    }
    this.emit("signal-updated", snapshot);
    return snapshot;
  }

  /**
   * Drive ended: invalidate EVERY signal bound to that drive, even if the
   * old price is still visible on the page (spec §15 critical test).
   */
  driveEnded(driveId: string): SignalSnapshot[] {
    const invalidated: SignalSnapshot[] = [];
    for (const [key, entry] of this.signals) {
      if (entry.snapshot.observed.driveId === driveId && !entry.snapshot.withdrawn) {
        const snapshot: SignalSnapshot = {
          ...entry.snapshot,
          state: "STALE",
          withdrawn: true,
          withdrawalReason: "DRIVE_ENDED",
          reasons: [
            `drive ${driveId} ended — signal invalidated; the visible price is no longer tied to a live possession`,
            ...entry.snapshot.reasons,
          ],
          evaluatedAt: new Date(this.now()).toISOString(),
        };
        this.signals.set(key, { ...entry, snapshot });
        invalidated.push(snapshot);
        this.emit("alert-withdrawn", snapshot);
        this.emit("signal-updated", snapshot);
      }
    }
    return invalidated;
  }

  /** Market element removed from the page. */
  remove(signalKey: string): void {
    const entry = this.signals.get(signalKey);
    if (!entry) return;
    const snapshot: SignalSnapshot = {
      ...entry.snapshot,
      withdrawn: true,
      withdrawalReason: "REMOVED",
      evaluatedAt: new Date(this.now()).toISOString(),
    };
    this.signals.delete(signalKey);
    this.emit("signal-removed", snapshot);
  }

  /** Apply a DOM change event batch. Returns affected snapshots. */
  applyChangeEvents(events: MarketChangeEvent[], lookupModel: (snapshot: SignalSnapshot) => ModelEvaluation | undefined, driveContext?: DriveContext): SignalSnapshot[] {
    const out: SignalSnapshot[] = [];
    for (const ev of events) {
      if (ev.kind === "REMOVED" && ev.signalKey) {
        this.remove(ev.signalKey);
        continue;
      }
      if (ev.market && ev.signalKey) {
        const entry = this.signals.get(ev.signalKey);
        const snapshot = this.observe(ev.signalKey, ev.market, {
          ...(entry?.snapshot.normalized ? { normalized: undefined } : {}), // re-normalize fresh
          model: lookupModelStub(lookupModel, entry?.snapshot),
          ...(driveContext ? { driveContext } : {}),
          visible: true,
        });
        out.push(snapshot);
      }
    }
    return out;
  }

  /** All live snapshots. */
  snapshots(): SignalSnapshot[] {
    return [...this.signals.values()].map((e) => e.snapshot);
  }

  get(signalKey: string): SignalSnapshot | undefined {
    return this.signals.get(signalKey)?.snapshot;
  }

  /** Prune signals idle beyond maxSignalIdleMs (e.g. after tab switch). */
  pruneIdle(): number {
    const nowMs = this.now();
    let pruned = 0;
    for (const [key, entry] of this.signals) {
      const age = nowMs - Date.parse(entry.snapshot.evaluatedAt);
      if (Number.isFinite(age) && age > this.maxSignalIdleMs) {
        this.signals.delete(key);
        pruned += 1;
      }
    }
    return pruned;
  }
}

function lookupModelStub(
  lookupModel: (snapshot: SignalSnapshot) => ModelEvaluation | undefined,
  previous: SignalSnapshot | undefined,
): ModelEvaluation | undefined {
  if (!previous) return undefined;
  return lookupModel(previous);
}

/** Re-evaluate every existing snapshot at a new time (freshness ticker). */
export function reevaluateAll(
  registry: SignalRegistry,
  opts: {
    modelLookup: (snapshot: SignalSnapshot) => ModelEvaluation | undefined;
    matchLookup?: (snapshot: SignalSnapshot) => import("./market-types.ts").MatchResult | undefined;
    driveContext?: DriveContext;
  },
): SignalSnapshot[] {
  const out: SignalSnapshot[] = [];
  for (const snap of registry.snapshots()) {
    if (snap.withdrawn) {
      out.push(snap);
      continue;
    }
    const model = opts.modelLookup(snap);
    const match = opts.matchLookup?.(snap);
    const refreshed = registry.observe(snap.signalKey, snap.observed, {
      normalized: snap.normalized,
      ...(match !== undefined ? { match } : {}),
      ...(model !== undefined ? { model } : {}),
      ...(opts.driveContext ? { driveContext: opts.driveContext } : {}),
      visible: true,
    });
    out.push(refreshed);
  }
  return out;
}
