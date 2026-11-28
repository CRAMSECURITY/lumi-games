# 012.4 DATA LIFECYCLE
- Expire pending video verification material after 30 days from submission (creation fallback); reset unverified review status and remove related queue references. Completed verification flags are retained.
- Remove completed verification request records after 30 days from creation.
- Remove stale administrative references to closed support tickets before existing 90-day deletion.
- Separate backup and retention error handling so common backup failures do not prevent cleanup.
- No database schema change. Review retention policy before deployment; backups and Telegram-hosted messages are not erased by this cleanup.
- Durable cross-service account deletion retries intentionally not added: current remote API deletes all data by user ID, so a delayed retry could erase a newly registered account. Requires generation-scoped deletion or tombstones and coordinated re-registration.
- Local tests: Python unittest discover 126 passed; npm test 59 passed. No live Telegram or Cloudflare testing.
