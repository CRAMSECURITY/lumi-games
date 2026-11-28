# 026.0 — LUMI EXPERIENCE

First design-system pass: a separate CSS layer after existing styles; shared focus, touch size, support text and transition tokens. City controls receive a 44px minimum height, disabled styling and navigation hover/press states. Secondary city copy is flat and normal weight. Four main views and city dialog use short opacity-only entrances when reduced motion is not requested. Original 3D geometry, assets, gestures, bot, API and age settings remain unchanged. No new dependencies or migrations.

Verification: 98/98 Node tests (one new static design-contract test). No device/browser visual test, performance benchmark, live Telegram/Cloudflare or Python rerun. Focus and animation rendering still require device verification. Next: device testing and measured loading optimization.
