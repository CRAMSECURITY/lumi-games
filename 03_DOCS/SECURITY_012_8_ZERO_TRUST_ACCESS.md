# 012.8 ZERO TRUST ACCESS

- Recheck active session and ban before returning private room and morning results, and session status.
- Guard automatic round progression SQL with active session and participant predicates; check authorization after advancement.
- Regression scenarios: ban during morning results read; session revocation immediately before round advance. Both passed in SQLite integration test. Full JS suite: 60 passed.
- No schema migration, visual changes or Python changes. Python suite not rerun.
- Additional database reads add latency; live Cloudflare load and D1 behavior not tested. Revocation after final authorization check but before response delivery remains possible; no guarantee of instantaneous revocation.
