# The blocker: historical prop lines

Everything in this repo is verifiable except the one thing that matters —
whether the model beats a real market. That requires historical *posted* prop
lines, and they are not free.

## Options, honestly ranked

| Source | Prop coverage | Cost | Notes |
|---|---|---|---|
| **The Odds API — historical** | 2023+ for player props, thinner before | ~$119–299/mo tier | Cleanest API. Historical props are billed per snapshot per market; a full backfill is expensive. Start with one season. |
| **OddsJam / OddsBlaze** | Deep, many books | $$$ (enterprise-ish) | Best coverage. Priced for funded operations. |
| **Unabated / Pinnacle scrape** | Sharp lines only | Free–low | Pinnacle doesn't post many NFL receiving props; limited. |
| **Kaggle / community dumps** | Sporadic, unverified | Free | Provenance unknown. Fine for a smoke test, not for a decision. |
| **Forward-collect your own** | Perfect fidelity | ~$100/mo + time | Start logging closing lines *this season*. In 8 weeks you have a real CLV sample. |

## The recommendation

Do the last one first. It costs almost nothing, it produces the only evidence
that would justify charging anyone, and it starts today. The 2026 season opens
in about a month — that's your collection window.

`agent.py` already has `log_picks()` and `record_closing()` wired for exactly
this. Run the agent every week, log the pick and the closing line, and let
`clv_report()` tell you the truth in November.

## Why CLV and not win rate

To detect a 2% edge from win/loss at 95% confidence you need roughly
**6,000 bets**. At 30 picks a week that is four seasons.

CLV converges far faster because it uses a continuous measurement per bet
instead of a binary one. A few hundred picks gives a usable read. If you must
know whether this works before betting real size, CLV is the only instrument
that answers in time.
