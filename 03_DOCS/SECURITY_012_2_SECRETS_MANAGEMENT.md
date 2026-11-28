# 012.2 SECRETS MANAGEMENT

- Standard root logging handlers in both bots redact known environment secrets and Telegram-shaped tokens after formatting, including exception text and URL-encoded values.
- Added .gitignore for local credentials, runtime databases, logs and backups. It does not remove previously tracked files or protect ZIP exports.
- 122 offline Python tests (5 new), 59 JavaScript tests passed. No changes to Mini App or DB schema.
- Limitations: direct print, external logging handlers, process memory, unknown secret encodings and historical logs are not covered. No live rotation, external secret manager or deployed infrastructure validation performed.
- Use environment variables or protected local configuration, Cloudflare secrets for Worker, never commit or distribute actual .env, .dev.vars, database or backup files. On exposure revoke Telegram tokens and rotate sync credentials on both ends. Retain old backup key securely until encrypted backups have been migrated and verified.
