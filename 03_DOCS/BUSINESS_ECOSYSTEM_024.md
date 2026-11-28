# 024.0 BUSINESS ECOSYSTEM — local integration release

Discover now has four quick navigation buttons: Afisha, People, My registrations, Create. They open the appropriate existing section and focus/scroll to the relevant control without submitting forms or making automatic requests. Existing signature cards, motion and typography remain. Clarified private preview versus consensual publishing, and external versus community registration.

Regression: 86 JS tests, 228 bot Python tests, 30 tool tests passed locally. Fixed eight marketplace test setup errors caused by the legacy test-only global SQLite connection patch by explicitly selecting the standard SQLite connection factory in marketplace tests. No production Python changes.

## Staging checklist
- Back up D1; apply migrations in order through 0011. Verify existing capacity values.
- Configure existing business directory/connect/moderation and event organizer/registration feature flags and authorized moderator IDs per earlier docs. Leave disabled until staging passes.
- Test two separate Telegram accounts and a separate moderator: publish/reject/withdraw business card; invite/accept/report/block; create/approve/cancel event; join/leave/full event; deletion and blocked access.
- Verify real device scrolling, reduced motion, layout at narrow widths, keyboard focus, date/time zone and cancellation visibility. Verify real D1 concurrency and live deployment.
- Review organizer legitimacy, event location safety and privacy before publishing. External events remain manually curated; no payment or notifications.
- Online dependency audit, owner signature and deployment approval remain outstanding. Not a production-approved release. No new migration or age-setting change.
