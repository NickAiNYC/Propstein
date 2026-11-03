# Payments: read before you build the storefront

## Stripe treats sports picks as restricted

Sports-betting-adjacent services sit in Stripe's restricted-business list.
Selling picks is not automatically prohibited, but it is reviewed, and accounts
get frozen after volume arrives rather than at signup — which is the worst
possible timing. Two specific triggers:

1. **Guaranteed-return or profit claims.** "Positive EV," "guaranteed profit,"
   "we win 62%" without substantiation. This is also an FTC deceptive-claims
   exposure independent of Stripe.
2. **Operating in a jurisdiction where the underlying activity is illegal**
   while accepting payment from it.

## Whop

Whop is purpose-built for this category and carries more of the compliance
weight, which is why the sports-pick market lives there. It still requires
accurate marketing claims. Whop's own guidelines prohibit guaranteed-win
framing.

## What you can safely claim

- Your **actual** documented record, with sample size and date range.
- Your methodology, in specifics.
- CLV performance, if you measure it.

## What you cannot

- "Positive EV" as a marketing claim before you have evidence for it. It is a
  quantitative assertion about future returns. Stated at point of sale without
  substantiation, it is the textbook definition of an unsubstantiated
  performance claim.
- Backtested returns presented as achieved returns.
- Win rates from a proxy-line simulation. (See `backtest.py` — the +10% ROI in
  that output is against a form-only baseline, not a book. Publishing it as a
  performance figure would be false.)

## Required disclosures

Responsible-gambling language, 21+/jurisdiction notice, and an explicit "not
financial advice" line on every surface. `api/main.py` ships them in the
response payload.
