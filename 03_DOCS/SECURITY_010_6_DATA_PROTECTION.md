# 010.6 DATA PROTECTION
Base: 010.5 ACCESS CONTROL. No UI or database schema changes.
- Automatic backups now require Fernet key; legacy plaintext opt-out no longer works. LUMI_AUTO_BACKUP=0 remains an explicit disable option, not recommended without external backup.
- Validate key, authenticate and quick-check today's backup before retention pruning. Corrupt copy or wrong key stops operation without pruning older copies; investigate and move corrupt copy manually before retrying.
- POSIX backup directory owned by service user with mode 0700. Use a dedicated backup directory; existing directory permissions will be tightened. Windows ACLs and trusted parent directories must be configured by operator.
- Retention default 7 days, range 1–3650. Legacy plaintext copies are not automatically removed: migrate securely and remove after verification. Historical keys must be retained separately until corresponding backups expire. Key rotation not automated; do not replace key without tested recovery plan.
- Working SQLite database is NOT encrypted by this change; deploy encrypted storage and verify D1/TLS separately. No independent live pentest. Backup snapshots use memory proportional to database size. Concurrent backup processes and hostile local users with directory access are not tested.
- 12 selected Python tests, 44 JS tests passed; no live Telegram testing.
