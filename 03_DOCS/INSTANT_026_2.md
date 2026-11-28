# 026.2 INSTANT
- Welcome poster remains immediately available; renderer is dynamically loaded after 650 ms only when welcome is visible, motion is enabled and saveData is off.
- Closing welcome or hiding the document cancels the timer and aborts ongoing model fetch; completed geometry is cached in memory. Renderer script itself may finish downloading after cancellation, but cannot mount stale content.
- Kigurumi model unchanged (7,637,356 bytes). Fixed scope of lazy drop renderer loader shared by hero gallery.
- No backend or age changes. 103 Node tests pass, including mocked cancellation tests; no mobile browser timings or Python rerun. Actual network bytes saved depend on browser/cache and dismissal time.
