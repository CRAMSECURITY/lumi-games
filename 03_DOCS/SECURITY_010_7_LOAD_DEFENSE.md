# LUMI 010.7 LOAD & DoS DEFENSE
Based on 010.6. Worker only; no migration or UI changes.
- Reject invalid or oversized declared POST lengths after edge rate limiting, before D1/authentication.
- Read JSON bodies into one fixed 4096-byte buffer; cap fragments at 8192 and total read time at 5 seconds (408). Do not await cancellation of rejected streams.
- Five local regression tests: early rejection, fragmentation, excessive empty fragments, stalled stream, cancellation that never resolves.
- Existing edge and per-user limits unchanged. Local Node tests are not a production load test; actual Cloudflare timeout behavior, concurrent request capacity, D1 latency, and Python bot load remain unverified. No live traffic generated. The 5-second deadline and fragment cap are provisional choices.
