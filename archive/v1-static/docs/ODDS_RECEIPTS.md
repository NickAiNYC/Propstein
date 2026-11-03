# Odds receipt contract

A quote may influence qualification, EV, or stake only when it is traceable to a stored provider response.

`provider_quote_id` is the SHA-256 hash of these ordered identity fields:

1. provider
2. event ID
3. bookmaker
4. market
5. outcome
6. point
7. provider last-update timestamp

Each verified quote must also carry an HTTPS provider source URL, a SHA-256 hash of the raw response, the provider update timestamp, and our fetch timestamp. The browser rejects incomplete receipts, malformed values, future timestamps, and quotes more than ten minutes old. Rejected quotes remain visible only as `DATA CHECK` with zero qualification and zero stake.

The raw response belongs in durable server-side storage. The hash detects changes; it does not make a mutable database immutable.

## Polymarket CLOB canonical receipts (v1.1, 2026-11-02)

CLOB/Gamma HTTP bodies carry volatile envelope fields (sequence numbers,
internal timestamps), so hashing raw bytes would make two honest pulls of the
same resting quote hash differently. For the Polymarket path the durable
receipt hashes a **canonical projection** (`polymarket_clob_quote.v1`) of the
quote-defining fields only — market id, question, slug, both outcome token
ids, both best-ask prices, both displayed ask depths — sorted keys, no
envelope noise.

The independent receipt check is then mechanical: ingestion pull #1 appends a
`ReceiptRecord` to `data/polymarket_receipt_log.json` (append-only, capped at
400 rows); the verification pass re-pulls the same outcome token books from
the CLOB, re-derives the canonical hash, and the **frozen verification.v1
engine** (`src/contracts/verification.py`) decides. With a single two-sided
publisher the V3 cross-book clause is structurally uncheckable
(`min_sharp_books=2`), so the engine ceiling on this feed is **OBSERVED:
receipt-matched, never VERIFIED**. VERIFIED stays forbidden until a second
sharp book exists (the ODDS_API_KEY path). The feed's evidence level is
published as `feed_status` (`LIVE_POLYMARKET_CLOB_RECEIPTED` /
`..._UNVERIFIED`) with `receipt_matched_quotes_count`; verified counts stay
structurally zero.

### Stamp binding: receipts certify the published content (v1.2, 2026-11-03)

A receipt certifies CONTENT, and the content it must certify is the quote the
feed publishes — the pass-1 capture. Only receipts whose canonical hash equals
the published quote's pass-1 hash are admissible evidence to the engine, so a
stamp requires the two CURRENT pulls to agree hash-for-hash. If the price
moves A→B between the ingestion pull and the verification pull, the pass-2 B
book cannot stamp the published A quote — even when an older B receipt sits in
the log (the moved book merely re-seeing its own earlier price). The engine
still renders every decision; the fetcher only curates which receipts count
as evidence. The `odds_freshness.yml` publication gate accepts both evidence
levels (`..._UNVERIFIED` and `..._RECEIPTED`, mirroring the frozen
`PolymarketMergedFeed` vocabulary) so a receipt-matched feed is published,
never blocked.
