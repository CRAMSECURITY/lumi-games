# LUMI 010.8 ERROR RESILIENCE
Base: 010.7 LOAD DEFENSE.
- Edge limiter exceptions and malformed responses fail closed (503), before database access.
- Missing DB or token returns a generic 503 without configuration names.
- Await asset fetch to catch asynchronous rejections; sanitize client response.
- Broken request streams become generic 400; existing size and time limits remain.
- Scheduled cleanup failure is logged and propagated with a generic error, not silently swallowed.
- Five regression tests added; npm test: 54 passed, 0 failed (Node 22.16.0). See test log.
- No migration, bot code, frontend or design changes. Production Cloudflare/Telegram, Python functional tests, dependency CVEs and real load not tested. No automatic retry of non-idempotent operations added; operational alerting and recovery remain separate tasks.
