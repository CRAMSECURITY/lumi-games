# 011.4 SMART CACHE MANAGEMENT
- Disposable browsing maps: 5000 active panels, 2000 users each for seen/deferred, 1000 IDs per user. Eviction can repeat suggestions or require reopening browsing. Persistent SQL limits unchanged.
- Hero PNG cache: 24 MiB of payloads and 96 entries, thread-safe; excludes temporary rendering allocations.
- At most 32 concurrent optional teaser notifications; new teasers skipped when full; cancellation awaited on shutdown.
- Clear own UI caches on account deletion. Other users' cached references may remain until eviction.
- 39 selected Python tests, 59 JS tests passed. aiogram unavailable, full Telegram integration and actual memory profiling not performed. FSM unchanged to avoid losing drafts. No migrations or visual changes.
