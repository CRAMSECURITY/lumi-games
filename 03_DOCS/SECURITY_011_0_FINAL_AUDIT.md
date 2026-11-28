# 011.0 FINAL SECURITY AUDIT — local release candidate
Based on 010.9. Only Worker readiness, authentication wire encoding and corresponding tests changed. UI and Python source unchanged.

- Health checks now prepare queries referencing all required columns of the six application tables. Existing tables with missing columns no longer produce a successful readiness status. This does not verify constraints/indexes or actual write permissions.
- Auth rejects malformed percent escapes and invalid UTF-8 before URLSearchParams canonicalization. Valid signed Unicode inputs and existing Telegram fixtures still pass. This is parser hardening, not evidence of an exploitable authentication bypass.
- 59 Node tests passed (2 new tests). 26 selected Python tests passed; ResourceWarning for unclosed SQLite connections observed and requires investigation. 6 dependency-gate unit tests passed; offline metadata checks passed for 133 npm entries. Offline check does not verify known CVEs.
- Full Python discovery is not a successful release test; see accompanying log. aiogram is absent. No live Telegram, Cloudflare, TLS, payment, device or load test performed. No independent penetration test or online CVE audit performed. Working database encryption, alerting and key rotation remain open. No new migration or secret required for this release beyond earlier requirements.
- Do not approve public launch based only on these tests. Use staging and run all outstanding checks first.
