# LUMI 012.6 — ACCOUNT CONSISTENCY

Based on 012.5. Worker now rechecks the exact session token hash, owner and expiration in the same SQL statement as rate counter updates, room creation, joining, answer submission and morning score writes. A deletion committed before the write invalidates the session and prevents the stale request from recreating deleted records. No schema migration beyond existing 0005 is needed.

Regression scenarios simulate a signed account deletion immediately before the morning score or room creation write, after authentication. Both writes are rejected and no user records are recreated. All 60 Node tests passed with Node 22.16 using the local SQLite D1 adapter. The scenarios are part of an existing integration test, not additional standalone tests.

Limitations: a stale request may receive a generic conflict/rate-limit response (room creation returns 429). In-flight reads and response delivery are not fully synchronized; existing ban checks are not part of this change. Cross-service account generation, durable deletion retries, real Cloudflare deployment and Python tests remain unverified. Python bot, UI and assets are unchanged.
