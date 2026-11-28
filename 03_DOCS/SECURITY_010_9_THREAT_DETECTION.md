# 010.9 THREAT DETECTION
Worker emits fixed structured security events for HTTP 401, 403, 413, 429, 500, 503 on API routes only. No request path, IP, headers, body, user ID or exception is included in these new events. Logging failures do not change responses. Existing Cloudflare logging configuration is unchanged; provider-added metadata must be reviewed separately.

57/57 Node tests passed, including three new telemetry tests. No migration or additional secret required. Python and UI unchanged.

Deployment: inspect Cloudflare Worker logs on staging; filter messages for component lumi-api and event. Configure external alerting and retention in the Cloudflare account, with thresholds based on normal traffic. This release does not install alerts, aggregate events, or automatically ban users. Per-response logging can increase costs during floods; review sampling and retention before public launch. No production deployment or real alert delivery was tested.
