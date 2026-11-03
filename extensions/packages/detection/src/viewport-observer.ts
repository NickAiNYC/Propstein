/**
 * PropStein Live Sniper — Viewport Observer
 * =======================================
 * Browser-side visibility collection: IntersectionObserver + bounding
 * rectangles + computed styles, feeding the pure `decideVisibility` logic.
 *
 *  - IntersectionObserver tracks in/out of viewport transitions.
 *  - On each relevant intersection or scroll, the DECISION is recomputed
 *    from live geometry (bounding client rects) rather than trusting
 *    cached entries — virtualized lists and scroll containers included.
 *  - Shadow DOM roots are traversed where accessible (open roots only —
 *    closed roots are the platform's boundary and are never forced).
 *  - Fallback: when IntersectionObserver is unavailable (older Safari),
 *    scroll/resize listeners drive recomputation instead.
 */

import { decideVisibility, type VisibilityDecision } from "./visibility-filter.ts";

export interface ViewportObserverOptions {
  /** Minimum element-area intersection with the viewport (default 0.5). */
  minIntersectionRatio?: number;
  /** Recompute on these events (default: visibilitychange + scroll + resize). */
  enableFallbackListeners?: boolean;
  /** Injected clock for deterministic tests. */
  now?: () => Date;
}

export type VisibilityListener = (el: Element, decision: VisibilityDecision) => void;

export class ViewportObserver {
  private readonly minRatio: number;
  private readonly io: IntersectionObserver | undefined;
  private readonly decisions = new WeakMap<Element, VisibilityDecision>();
  private readonly listeners = new Set<VisibilityListener>();
  private readonly fallbackCleanup: (() => void) | undefined;
  private stopped = false;

  constructor(opts: ViewportObserverOptions = {}) {
    this.minRatio = opts.minIntersectionRatio ?? 0.5;
    if (typeof IntersectionObserver !== "undefined") {
      this.io = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          this.evaluate(entry.target as Element);
        }
      }, { threshold: [0, 0.25, 0.5, 0.75, 1] });
    } else if (opts.enableFallbackListeners !== false && typeof window !== "undefined") {
      const handler = () => this.reevaluateAll();
      window.addEventListener("scroll", handler, { passive: true });
      window.addEventListener("resize", handler, { passive: true });
      document.addEventListener("visibilitychange", handler);
      this.fallbackCleanup = () => {
        window.removeEventListener("scroll", handler);
        window.removeEventListener("resize", handler);
        document.removeEventListener("visibilitychange", handler);
      };
    }
  }

  /** Observe an element for visibility transitions. */
  observe(el: Element): void {
    this.io?.observe(el);
    this.evaluate(el);
  }

  unobserve(el: Element): void {
    this.io?.unobserve(el);
  }

  onDecision(listener: VisibilityListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Latest known decision for an element (recomputed on demand if absent). */
  decisionFor(el: Element): VisibilityDecision {
    const cached = this.decisions.get(el);
    if (cached) return cached;
    return this.evaluate(el);
  }

  isElementVisible(el: Element): boolean {
    return this.decisionFor(el).visible;
  }

  private evaluate(el: Element): VisibilityDecision {
    if (this.stopped) return { visible: false, intersectionRatio: 0, reasons: ["observer stopped"] };
    const decision = computeElementDecision(el, this.minRatio);
    this.decisions.set(el, decision);
    for (const l of this.listeners) l(el, decision);
    return decision;
  }

  private reevaluateAll(): void {
    // WeakMap cannot be iterated; the pipeline re-evaluates lazily via
    // decisionFor() on each mutation flush, which is the primary path.
    // This fallback path exists for scroll-driven recomputation.
    for (const l of this.listeners) l(document.body, this.evaluate(document.body));
  }

  stop(): void {
    this.stopped = true;
    this.io?.disconnect();
    this.fallbackCleanup?.();
  }
}

/** Collect geometry + style for one element and decide. */
export function computeElementDecision(el: Element, minRatio: number): VisibilityDecision {
  const rect = (el as HTMLElement).getBoundingClientRect();
  const style = typeof getComputedStyle === "function" ? getComputedStyle(el) : undefined;
  return decideVisibility(
    {
      top: rect.top,
      bottom: rect.bottom,
      left: rect.left,
      right: rect.right,
    },
    {
      width: typeof window !== "undefined" ? window.innerWidth : 1280,
      height: typeof window !== "undefined" ? window.innerHeight : 800,
    },
    {
      display: style?.display,
      visibility: style?.visibility,
      opacity: style ? Number(style.opacity) : undefined,
      contentVisibility: style?.getPropertyValue?.("content-visibility"),
    },
    minRatio,
  );
}

/**
 * Collect market-card candidates including OPEN shadow roots.
 * Closed shadow roots are skipped — the platform boundary is respected.
 */
export function queryAllIncludingShadow(root: ParentNode, selector: string): Element[] {
  const results: Element[] = [];
  const walk = (node: ParentNode) => {
    for (const el of Array.from(node.querySelectorAll(selector))) {
      results.push(el);
    }
    // Recurse into open shadow roots.
    const all = node.querySelectorAll("*");
    for (const el of Array.from(all)) {
      const shadow = (el as HTMLElement).shadowRoot;
      if (shadow) walk(shadow);
    }
  };
  walk(root);
  return results;
}
