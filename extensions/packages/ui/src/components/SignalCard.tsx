/**
 * PropStein Live Sniper — SignalCard component (spec §11).
 * Terminal-grade card. Never shows fake numbers: missing data renders "—".
 */
import type { SignalCardViewModel } from "../view-models.ts";

export interface SignalCardProps {
  vm: SignalCardViewModel;
  onViewAnalysis?: (key: string) => void;
}

export function SignalCard({ vm, onViewAnalysis }: SignalCardProps) {
  return (
    <article className={`signal-card signal-card--${vm.tone}${vm.withdrawn ? " signal-card--withdrawn" : ""}`}>
      <div className="signal-card__head">
        <span className="signal-card__league">{vm.leagueLine}</span>
        <span className={`signal-card__state signal-card__state--${vm.tone}`}>{vm.statusLabel}</span>
      </div>
      <h3 className="signal-card__title">{vm.marketTitle}</h3>
      <div className="signal-card__who">
        <div>{vm.playerLine}</div>
        <div>{vm.selectionLine}</div>
      </div>
      <dl className="signal-card__grid">
        <div className="row">
          <dt>SPORTSBOOK PRICE</dt>
          <dd className="num">{vm.sportsbookPrice}</dd>
        </div>
        <div className="row">
          <dt>BREAK-EVEN</dt>
          <dd className="num">{vm.breakEven}</dd>
        </div>
        <div className="row">
          <dt>MODEL PROBABILITY</dt>
          <dd className="num">{vm.modelProbability}</dd>
        </div>
        <div className="row">
          <dt>ESTIMATED EV</dt>
          <dd className={`num num--${vm.evTone}`}>{vm.estimatedEv}</dd>
        </div>
        {vm.probabilityEdge !== null && (
          <div className="row">
            <dt>PROBABILITY EDGE</dt>
            <dd className="num">{vm.probabilityEdge}</dd>
          </div>
        )}
        {vm.fairOdds !== null && (
          <div className="row">
            <dt>FAIR ODDS</dt>
            <dd className="num">{vm.fairOdds}</dd>
          </div>
        )}
      </dl>
      <div className="signal-card__foot">
        <span>SOURCE: {vm.source}</span>
        <span>MARKET STATUS: {vm.marketStatus}</span>
        <span>MODEL: {vm.model}</span>
        <span>QUOTE AGE: {vm.quoteAge}</span>
      </div>
      {vm.reasons.length > 0 && (
        <ul className="signal-card__reasons">
          {vm.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
      <div className="signal-card__actions">
        <button type="button" className="btn btn--ghost" onClick={() => onViewAnalysis?.(vm.key)}>
          VIEW ANALYSIS
        </button>
      </div>
    </article>
  );
}
