/**
 * GET /api/extension/health — kill-switch state, adapter versions, posture.
 * The extension polls this; a disabled state is explicit, never silent.
 */

import { killSwitchActive } from '@/lib/domain/tokens';
import { ok } from '@/lib/server/api';

export const runtime = 'nodejs';

export async function GET() {
  return ok({
    status: killSwitchActive('extension') ? 'DISABLED' : 'ENABLED',
    killSwitch: { extension: killSwitchActive('extension'), marketIntelligence: killSwitchActive('market_intelligence') },
    adapters: [
      { id: 'visible-quote-observer', version: '1.3.0', posture: 'read-only', selectorDrift: 'monitored' },
      { id: 'slip-screenshot-capture', version: '1.1.2', posture: 'read-only', selectorDrift: 'monitored' },
    ],
    posture: {
      betPlacement: 'not supported by design',
      betPreparation: 'not supported by design',
      credentialCollection: 'not supported by design',
      antiBotBypass: 'not supported by design',
      modelCoverage: 'NO MODEL COVERAGE for real books until a licensed possession-level feed and calibration corpus exist',
    },
    checkedAtUtc: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
  });
}
