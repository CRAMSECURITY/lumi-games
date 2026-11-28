# 012.5 SECURE ACCOUNT LIFECYCLE
- Required D1 migration 0005_account_deletion.sql before Worker deployment.
- Signed deletion receipt (user ID + signed timestamp) inserted in the same D1 batch as deletion. Duplicate signed requests return success without deleting again. Failed batches must roll back atomically.
- A 120-second login barrier blocks new sessions and pre-barrier Telegram launch data via the atomic session INSERT. Existing sessions are revoked by deletion. Receipt cleanup occurs one hour after barrier expiry. Bot informs user to reopen Mini App after two minutes.
- No automatic delayed retry or generation-scoped account deletion implemented. A new signed deletion request is still user-ID scoped; already in-flight authenticated requests may race deletion. Local account registration is not gated by this remote barrier. Full cross-service lifecycle coordination remains open. Test on staging D1/Telegram before deploying. Minimal ID receipts temporarily retained.
- Local Node tests: 60 passed. Python tests: see attached output. UI assets unchanged.
