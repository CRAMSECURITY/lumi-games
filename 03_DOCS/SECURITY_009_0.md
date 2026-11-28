# LUMI 009.0 — EDGE DEFENSE
- Added Cloudflare rate limiting before Telegram verification and D1 operations on API routes except public health. Missing binding fails closed (503); denied requests return 429.
- Existing per-user database limiter remains. Edge threshold is 600 requests/minute per connecting IP per Cloudflare location, approximate, not global. Shared mobile IPs can cause false positives; tune after load tests. Missing IP shares an unknown bucket. Trust CF-Connecting-IP only on Cloudflare ingress; do not expose an alternate origin or untrusted Worker proxy.
- Disabled automatic invocation logs to reduce exposure of room invite codes in URLs; custom error logs remain. Existing logs and other Cloudflare logging products require separate review.
- Verify namespace 91001 is unused in your Cloudflare account before deployment; select a unique positive integer if necessary. Test deployment in staging. No new database migration; previous 0002 migration still required. Public health is unchanged. WAF and distributed DDoS controls are separate.
- Local tests: 32/32 Node tests; simulated rate-limit binding, not live Cloudflare. Python bot and UI untouched. No production deployment or claims of complete security.
- References: https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/ and https://developers.cloudflare.com/workers/observability/logs/workers-logs/
- Remaining: shared sanctions, session replay and account lifecycle, main database encryption, age assurance, dependency scans, load testing and live payment testing.
