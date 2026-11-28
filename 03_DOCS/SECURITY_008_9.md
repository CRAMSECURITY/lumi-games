# LUMI 008.9 — targeted adversarial review

Changes relative to 008.8:
- Reject ambiguous delimiters and key names in signed Telegram initData; regression test included.
- Hide current-round scores until round completion, including from the opponent; existing integration test expanded.
- Accept only pending premium orders and serialize successful-payment processing with BEGIN IMMEDIATE. Python syntax checked, live payment and full bot tests not run (aiogram unavailable).
- Require encrypted backups by default. Existing installations with a database must configure LUMI_BACKUP_KEY before launching, using instructions in PERFORMANCE_008_8.md. Preserve key separately and test restoration. Explicit legacy opt-out LUMI_REQUIRE_ENCRYPTED_BACKUP=0 is not recommended. Existing plaintext backups are not automatically encrypted or removed.

Tests: npm test 29/29; Python syntax checked; backup tests run separately. No production deployment. UI assets unchanged.

Open risks / next actions: unified account suspension and account deletion across Worker and bot; replay of valid initData within its lifetime; predictable limited puzzle bank; client-authoritative casual scores (do not reward these); pre-auth edge abuse protection and live rate-limit testing; encryption of primary data, secret rotation, audit logs, dependency advisory scan, age assurance, operational restore, real payments, independent penetration test. No guarantee of absence of vulnerabilities. Do not deploy directly to production.
