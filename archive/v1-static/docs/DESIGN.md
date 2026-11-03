# Design System

## Design Direction

Warm Clinical Luxury: a high-density quantitative terminal that prioritizes functional trust, calm scanning, and explicit execution state over decorative urgency.

The signature moment is the transition from a model signal to a verified, book-specific action: the interface should make the price, freshness, blocking rules, and risk allocation understandable in one scan.

## Typography

Pending Phase 4 review.

## Tokens

Pending Phase 4 review.

## Components

| Component | Decision | Status |
|---|---|---|
| Execution trust boundary | All price-dependent actions consume one centralized actionable-state decision, and the mutation path rechecks it. | implemented |
| Execution slip | Show book, timestamp, line, odds, fair value, edge, stake, and any blocking reasons before ledger confirmation. | implemented |
| Feed-state fallback | Stale or unverified data becomes historical/research mode without live execution affordances. | implemented |
| Execution decision | A pure decision object evaluates entitlement, receipt verification, quote completeness, freshness, market closure, gate, and volatility before any action is rendered or stored. | implemented |
| Ledger confirmation | A ledger entry represents a user-confirmed external wager, not a recommendation or staged idea. | implemented |
| Research note | Blocked opportunities may be retained separately without being represented as executed wagers. | accepted; future scope |

## UX Audit Findings

| Issue | Heuristic | Severity (0-4) | Fix | Status |
|---|---|---:|---|---|
| Refresh mutates static quote/EV data and then describes it as verified live movement. | Visibility of system status; consistency and standards | 4 | Remove production simulation, keep provider payloads immutable, and derive labels only from receipt state. Owner: engineering, P0. | fixed |
| Unverified rows render an enabled ledger control despite the stated fail-closed policy. | Error prevention | 4 | Render price-dependent controls only when the centralized execution guard returns actionable; otherwise show the blocking reason. Owner: engineering, P0. | fixed |
| `logBet()` does not enforce verification, freshness, gate, closed-state, or quote completeness. | Error prevention; user control | 4 | Enforce the same trust-boundary guard inside the mutation path and reject invalid entries before storage. Owner: engineering, P0. | fixed |
| Paid membership is selectable through client-side controls and persisted in `localStorage`. | Consistency and standards; error prevention | 4 | Remove the production tier simulator and derive entitlements from a server-validated session. Owner: engineering, P0. | client escalation fixed; authenticated server hookup pending |
| Current slate reports stale odds, zero verified quotes, and zero actionable rows while retaining live controls. | Visibility of system status; match with real world | 3 | Enter explicit historical/research mode and remove live execution affordances until a verified feed recovers. Owner: engineering, P0. | fixed |
| “One-tap confirm” opens generic player detail instead of an execution review. | Match with real world; recognition rather than recall | 3 | Open a focused review slip containing executable price, provenance, freshness, model edge, stake, and blockers. Owner: product/engineering, P1. | fixed |
| Refresh failure is console-only and retry is effectively a page reload. | Error recovery; visibility of system status | 3 | Preserve the last trusted snapshot and show refreshing, last checked, failure cause, and retry feedback inline. Owner: engineering, P1. | accepted |
| Table explanations use hover-only `title` text. | Help and documentation; accessibility | 2 | Replace spans with keyboard- and touch-accessible help buttons/popovers. Owner: frontend, P2. | fixed for model-only state |
| The full 390-row slate renders at once. | Aesthetic and minimalist design; efficiency | 2 | Default to decision buckets and progressively render or virtualize full research results. Owner: frontend, P2. | accepted |
| Warning dialogs allow users to override volatility halts and create wager records. | Norman gulf; error prevention | 4 | Replace warnings with a hard constraint; explain the halt and retain research-only inspection. Owner: engineering, P0. | fixed |
| An ambiguous plus control maps directly to ledger mutation. | Norman gulf; mapping | 3 | Rename the action `Review play`, open a complete execution review, and require explicit external-wager confirmation. Owner: product/engineering, P1. | fixed |
| Ledger additions and removals share a toggle control despite different meanings. | Norman gulf; conceptual model | 3 | Use deliberate confirmation for additions and retain undo for removals. Owner: frontend, P1. | accepted |

### Error-Prevention State Model

| State | Constraint | Feedback |
|---|---|---|
| Verified, fresh, entitled, complete, clears gate | Allow review | Book, quote age, edge, and stake preview |
| Verified but caution threshold exceeded | Require a refreshed price/news check before review | Exact caution reason in amber |
| Unverified or incomplete receipt | Hard block | “Price unverified—refresh or choose another book.” |
| Stale feed | Research mode; no live ledger mutation | Last trusted timestamp and retry action |
| Closed market | Hard block | Market closure state and time when known |
| Volatility or team halt | Hard block with no override | Specific line-movement or team-lock reason |
| Below gate | Research/watchlist only | Distance from configured gate |
| Model only | Model inspection only | No sportsbook quote available |
| Missing entitlement | Server-enforced denial | Upgrade path; no client tier selector |
| Refresh failure | Preserve last trusted snapshot | Failure reason, last trusted time, and retry |

Constraint replaces warning for unverified, stale, closed, unauthorized, incomplete, below-gate, and volatility-halted states. Undo remains appropriate for watchlist changes and ledger removal. Creation of a claimed wager record requires explicit confirmation because PROP·WIRE cannot reverse an external sportsbook action.

### Trunk Test

| Question | Result | Finding |
|---|---|---|
| What site is this? | Pass | Logo and PROP·WIRE identity are immediate. |
| What page is this? | Partial | “Slate” is inferred rather than explicitly titled. |
| What are the major sections? | Pass | Slate, Watch, Ledger, and Audit are visible on mobile. |
| What can I do here? | Partial | The plus control ambiguously suggests execution while only logging a ledger entry. |
| Where am I? | Partial | Mobile navigation is explicit; desktop hierarchy is less clear. |
| Where is search? | Pass | Search is visible in the header. |

Current UX heuristic score: **3/10**. The production-like interface contains multiple severity-4 trust-boundary violations, so polish cannot raise the score until those paths are constrained.

Current error-prevention score: **4/10**. Discoverability and limited undo behavior exist, but constraints and system feedback do not yet match the product’s trust claims.

## Microinteraction Inventory

Pending Phase 5 review.
