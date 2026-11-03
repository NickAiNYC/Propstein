/**
 * PropStein Live Sniper — EntitlementGate (spec §9, §11).
 *
 * CRITICAL DESIGN RULE (audit finding S-2): the tier shown here comes ONLY
 * from the server-verified session — never from a forgeable client-side
 * localStorage flag. Free users see the feature preview; premium signals
 * render only for verified Pro sessions. When the backend says expired, the
 * gate fails closed.
 */

export type EntitlementState =
  | { kind: "signed-out" }
  | { kind: "pro"; expiresAtIso: string; provider: string }
  | { kind: "free" }
  | { kind: "expired" };

export function EntitlementGate({
  state,
  onSignIn,
  onOpenPricing,
}: {
  state: EntitlementState;
  onSignIn?: () => void;
  onOpenPricing?: () => void;
}) {
  if (state.kind === "pro") {
    const minsLeft = Math.max(0, Math.round((Date.parse(state.expiresAtIso) - Date.now()) / 60_000));
    return (
      <div className="entitlement entitlement--pro">
        <span className="entitlement__tier">PRO · VERIFIED</span>
        <span className="entitlement__detail">via {state.provider} · session renews in {minsLeft}m</span>
      </div>
    );
  }
  if (state.kind === "expired") {
    return (
      <div className="entitlement entitlement--expired">
        <span className="entitlement__tier">SESSION EXPIRED</span>
        <span className="entitlement__detail">Protected model responses are unavailable until you re-authenticate.</span>
        <button type="button" className="btn btn--primary" onClick={onSignIn}>SIGN IN</button>
      </div>
    );
  }
  if (state.kind === "free") {
    return (
      <div className="entitlement entitlement--free">
        <span className="entitlement__tier">FREE PREVIEW</span>
        <span className="entitlement__detail">
          Live Sniper signals are a PropStein Pro feature. The panel previews the interface; premium model output stays locked.
        </span>
        <button type="button" className="btn btn--primary" onClick={onOpenPricing}>UPGRADE TO PRO</button>
      </div>
    );
  }
  return (
    <div className="entitlement entitlement--signedout">
      <span className="entitlement__tier">SIGN IN REQUIRED</span>
      <span className="entitlement__detail">Connect your PropStein membership to activate Live Sniper.</span>
      <button type="button" className="btn btn--primary" onClick={onSignIn}>SIGN IN</button>
    </div>
  );
}
