/**
 * PropStein — extension safety tests.
 *
 * Read-only posture: scopes are fixed; forbidden scopes are not issuable;
 * revocation works; the kill switch refuses session issuance; the API surface
 * contains no bet placement/preparation/submission routes; the web app never
 * requests or stores sportsbook credentials.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { readFileSync, readdirSync, statSync, existsSync } from 'fs';
import { join } from 'path';
import {
  EXTENSION_SCOPES,
  FORBIDDEN_SCOPES,
  decodeToken,
  issueExtensionSession,
  issueToken,
  killSwitchActive,
  revocationStore,
  setKillSwitch,
  verifyToken,
} from '../../src/lib/domain/tokens';
import { decideAlert, ALERT_TEMPLATES } from '../../src/lib/domain/alerts';
import { lintCopy } from '../../src/lib/domain/copy-lint';

const globalAny = globalThis as unknown as { __pstTestUserSeq?: number };

describe('extension session safety', () => {
  it('extension scopes are read-only observation plus ledger append only', () => {
    expect([...EXTENSION_SCOPES]).toEqual(['market.observe.readonly', 'ledger.append']);
  });

  it('no forbidden scope is issuable', () => {
    for (const scope of FORBIDDEN_SCOPES) {
      expect([...EXTENSION_SCOPES]).not.toContain(scope);
    }
    expect(FORBIDDEN_SCOPES).toContain('bet.place');
    expect(FORBIDDEN_SCOPES).toContain('credentials.read');
  });

  it('issued extension tokens carry the readonly scopes and verify', () => {
    const sub = `user-${(globalAny.__pstTestUserSeq = (globalAny.__pstTestUserSeq ?? 0) + 1)}`;
    const issued = issueExtensionSession(sub, 'pro');
    expect(issued.ok).toBe(true);
    if (issued.ok) {
      const claims = decodeToken(issued.token);
      expect(claims?.scope).toEqual(['market.observe.readonly', 'ledger.append']);
      expect(claims?.sub).toBe(sub);
      expect(verifyToken(issued.token).ok).toBe(true);
    }
  });

  it('revocation takes effect immediately', () => {
    const { token, claims } = issueToken('u-revoke', 'pro', ['market.observe.readonly']);
    expect(verifyToken(token).ok).toBe(true);
    revocationStore.revoke(claims.jti, claims.exp);
    const v = verifyToken(token);
    expect(v.ok).toBe(false);
    if (!v.ok) expect(v.reason).toBe('revoked');
  });

  it('tampered tokens are rejected (HMAC verification)', () => {
    const { token } = issueToken('u-tamper', 'pro', ['market.observe.readonly']);
    const parts = token.split('.');
    const tampered = `${parts[0]}X.${parts[1]}`;
    expect(verifyToken(tampered).ok).toBe(false);
  });

  it('expired tokens are rejected', () => {
    const now = Math.floor(Date.now() / 1000);
    const { token } = issueToken('u-exp', 'pro', ['market.observe.readonly'], now - 3600);
    const v = verifyToken(token, now);
    expect(v.ok).toBe(false);
    if (!v.ok) expect(v.reason).toBe('expired');
  });

  it('kill switch active -> session issuance is refused with an explicit state', () => {
    setKillSwitch('extension', true);
    try {
      expect(killSwitchActive('extension')).toBe(true);
      const issued = issueExtensionSession('u-kill', 'pro');
      expect(issued.ok).toBe(false);
      if (!issued.ok) expect(issued.reason).toBe('KILL_SWITCH_ACTIVE');
    } finally {
      setKillSwitch('extension', false);
    }
  });
});

describe('API surface safety (no wagering capability by construction)', () => {
  function walk(dir: string): string[] {
    const out: string[] = [];
    if (!existsSync(dir)) return out;
    for (const name of readdirSync(dir)) {
      const full = join(dir, name);
      if (statSync(full).isDirectory()) out.push(...walk(full));
      else out.push(full);
    }
    return out;
  }

  it('no route path places, prepares, or submits wagers', () => {
    const routes = walk(join(process.cwd(), 'src/app/api'));
    const routeFiles = routes.filter((f) => f.endsWith('route.ts'));
    expect(routeFiles.length).toBeGreaterThan(15);
    const forbiddenPath = /(bet|wager|place|submit|cashout|cash-out|deposit)/i;
    const offenders = routeFiles.filter((f) => forbiddenPath.test(f));
    expect(offenders).toEqual([]);
  });

  it('ledger routes expose no PUT/PATCH mutation handlers', () => {
    const ledgerRoutes = walk(join(process.cwd(), 'src/app/api/ledger'))
      .filter((f) => f.endsWith('route.ts'))
      .map((f) => ({ f, source: readFileSync(f, 'utf8') }));
    for (const { f, source } of ledgerRoutes) {
      expect(source, `${f} must not export PUT`).not.toMatch(/export\s+async\s+function\s+PUT/);
      expect(source, `${f} must not export PATCH`).not.toMatch(/export\s+async\s+function\s+PATCH/);
      expect(source, `${f} must not export DELETE`).not.toMatch(/export\s+async\s+function\s+DELETE/);
    }
  });

  it('no credential or balance collection anywhere in server code', () => {
    const serverFiles = walk(join(process.cwd(), 'src')).filter((f) => f.endsWith('.ts') || f.endsWith('.tsx'));
    const offenders = serverFiles.filter((f) => {
      const source = readFileSync(f, 'utf8');
      return /(sportsbookPassword|bookCredential|accountBalance|betSlipSubmit)/.test(source);
    });
    expect(offenders).toEqual([]);
  });
});

describe('alert safety', () => {
  const baseCtx = {
    enabledTypes: new Set(['quote_changed', 'quote_aged', 'player_status', 'market_suspended', 'closing_available', 'entry_settled', 'entry_unevaluable'] as const),
    mutedEntryIds: new Set<string>(),
    pushesSentToday: 0,
    nowUtc: '2026-11-08T19:00:00Z',
  };

  it('alert templates are factual and lint-clean', () => {
    const samples = [
      ALERT_TEMPLATES.quoteChanged(-115, -135),
      ALERT_TEMPLATES.quoteAged(9),
      ALERT_TEMPLATES.playerStatus('Questionable', 'Out'),
      ALERT_TEMPLATES.marketSuspended(),
      ALERT_TEMPLATES.closingAvailable('DEMO-CLOSE-1 (simulated)'),
      ALERT_TEMPLATES.entrySettled('settled'),
      ALERT_TEMPLATES.entryUnevaluable('stale'),
    ];
    for (const s of samples) expect(lintCopy(s)).toEqual([]);
  });

  it('alerts are suppressed when the type is disabled by preference', () => {
    const d = decideAlert(
      {
        ledgerEntryId: 'l1', type: 'quote_changed', message: ALERT_TEMPLATES.quoteChanged(-115, -135),
        snapshotTimeUtc: '2026-11-08T18:59:00Z', sourceProvider: 'P', urgent: false, capturedAtUtc: '2026-11-08T18:59:00Z',
      },
      { ...baseCtx, enabledTypes: new Set(['entry_settled' as const]) },
    );
    expect(d.deliver).toBe(false);
    if (!d.deliver) expect(d.reason).toBe('DISABLED_BY_PREFERENCE');
  });

  it('daily push cap suppresses urgent alerts beyond 3 per user', () => {
    const candidate = {
      ledgerEntryId: 'l1', type: 'market_suspended' as const, message: ALERT_TEMPLATES.marketSuspended(),
      snapshotTimeUtc: '2026-11-08T18:59:00Z', sourceProvider: 'P', urgent: true, capturedAtUtc: '2026-11-08T18:59:00Z',
    };
    expect(decideAlert(candidate, { ...baseCtx, pushesSentToday: 3 }).deliver).toBe(false);
    expect(decideAlert(candidate, { ...baseCtx, pushesSentToday: 2 }).deliver).toBe(true);
  });

  it('unverifiable freshness suppresses the alert (STALE QUOTE family)', () => {
    const d = decideAlert(
      {
        ledgerEntryId: 'l1', type: 'quote_changed', message: ALERT_TEMPLATES.quoteChanged(-115, -135),
        snapshotTimeUtc: '2026-11-08T18:59:00Z', sourceProvider: 'P', urgent: false, capturedAtUtc: null,
      },
      baseCtx,
    );
    expect(d.deliver).toBe(false);
    if (!d.deliver) expect(d.reason).toBe('STALE_SUPPRESSED');
  });

  it('muted entries are suppressed', () => {
    const d = decideAlert(
      {
        ledgerEntryId: 'l1', type: 'quote_changed', message: ALERT_TEMPLATES.quoteChanged(-115, -135),
        snapshotTimeUtc: '2026-11-08T18:59:00Z', sourceProvider: 'P', urgent: false, capturedAtUtc: '2026-11-08T18:59:00Z',
      },
      { ...baseCtx, mutedEntryIds: new Set(['l1']) },
    );
    expect(d.deliver).toBe(false);
    if (!d.deliver) expect(d.reason).toBe('MUTED');
  });

  it('a lint-violating template would be rejected (fail closed)', () => {
    const d = decideAlert(
      {
        ledgerEntryId: 'l1', type: 'quote_changed', message: 'This is a lock. Bet now.',
        snapshotTimeUtc: '2026-11-08T18:59:00Z', sourceProvider: 'P', urgent: false, capturedAtUtc: '2026-11-08T18:59:00Z',
      },
      baseCtx,
    );
    expect(d.deliver).toBe(false);
    if (!d.deliver) expect(d.reason).toBe('LINT_REJECTED');
  });
});
