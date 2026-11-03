# Customer

## Job Statement

When I find a possible market edge before the line moves, I want to verify the price and exposure, so I can act quickly without taking an untrusted or stale bet.

## Job Dimensions

| Dimension | Desired progress | Current underdelivery |
|---|---|---|
| Functional | Move from a model signal to a current, book-specific, correctly sized action before the market changes. | Price verification and execution are fragmented; model-only and stale states interrupt the path to action. |
| Emotional | Feel calm and certain that the displayed edge is real, current, and bounded by disciplined risk controls. | Ambiguous freshness and verification states force the user to second-guess whether an apparently strong edge is safe to act on. |
| Social | Operate with the discipline and clarity of a professional quantitative bettor. | Manual calculations and switching among sportsbook tabs makes the workflow feel improvised rather than controlled. |

The functional dimension is the worst underdelivery. It directly weakens the emotional and social dimensions because an unverified price cannot support confidence or professional discipline.

## Forces of Progress

| Force | Evidence or working hypothesis | Product implication |
|---|---|---|
| Push | Cross-book checking, stake sizing, and stale-line detection are manual and slow. | Collapse verification and sizing into the decision row and execution flow. |
| Pull | One terminal can combine model fair value, current price, freshness, and exposure guidance. | Make the trusted next action obvious without hiding the supporting evidence. |
| Anxiety | The quote may be stale, unverified, soft, or disconnected from the displayed model edge. | Fail closed, name the book and timestamp, and explain why action is blocked. |
| Habit | Users already know how to open several books, compare prices, and calculate stakes manually. | Preserve familiar book/line/odds language while removing duplicate work. |

## Big Hire and Little Hire

- Big Hire: The user decides whether PROP·WIRE appears rigorous enough to try or pay for.
- Little Hire: On every slate, the user decides whether to trust the displayed edge enough to verify and act before the line moves.
- Primary leak: Little Hire. The repeated execution workflow is the first optimization target.

## Competing Alternatives

| Alternative | Why hired | Weakness for this job |
|---|---|---|
| OddsJam | Fast cross-book positive-EV and arbitrage discovery. | Dense workflow and limited explanation of the model context behind a decision. |
| Props.cash | Accessible historical hit-rate research and visual exploration. | Retrospective evidence does not complete live price verification or disciplined execution. |
| Action Network / consumer trackers | Familiar tracking, editorial context, and consensus. | Community and media signals do not replace book-specific quantitative verification. |
| Sportsbook tabs plus calculator or spreadsheet | Direct access to executable prices with full manual control. | Slow, error-prone, and cognitively expensive when lines move quickly. |
| Screenshots, chat groups, or memory | Low-cost discovery and social confirmation. | Provenance, freshness, reproducibility, and risk sizing are weak or absent. |
| Non-consumption | Avoid placing a bet when verification is too costly or confidence is too low. | Protects bankroll but forfeits legitimate time-sensitive opportunities. |

## Evidence Status

The job model is currently grounded in competitive analysis, product-state audits, and the confirmed product direction. Direct switch interviews and observed task sessions are still required to validate the emotional and social dimensions, the four forces, and the exact causes of Little Hire failure.

Current JTBD score: **8/10**. The job is solution-independent, all dimensions and forces are mapped, non-consumption is included, and the Little Hire is explicit. The remaining gap is direct behavioral evidence from customer interviews.
