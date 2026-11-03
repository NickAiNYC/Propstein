// src/lib/executionGate.ts

/**
 * Evaluates whether an edge percentage clears the user's execution hurdle gate.
 * Normalizes both values to 1 decimal place to ensure 100% parity with what the
 * user sees rendered in the UI (preventing 9.96% formatted as 10.0% from being
 * marked SUB_GATE when user gate is set to 10.0%).
 */
export function evaluateGate(edgePct: number, userGate: number): 'ACTIVE' | 'SUB_GATE' {
  // 1. Round both to 1 decimal place to match the UI display exactly
  const roundedEdge = Math.round(edgePct * 10) / 10;
  const roundedGate = Math.round(userGate * 10) / 10;

  // 2. Compare the rounded values
  if (roundedEdge >= roundedGate) {
    return 'ACTIVE';
  }
  return 'SUB_GATE';
}
