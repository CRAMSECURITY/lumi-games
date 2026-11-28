// Fixed vocabulary only. Never log request headers, paths, bodies, IDs or exceptions.
const kinds = Object.freeze({401:'auth_rejected',403:'access_denied',413:'body_too_large',429:'rate_limited',500:'internal_failure',503:'service_unavailable'});
export function securityEvent(status, sink = console) {
 const event = kinds[status];
 if (!event || !Number.isInteger(status)) return;
 // Logging failure must not change the original response.
 try { sink.warn(JSON.stringify({component:'lumi-api',schema:1,event,status})); } catch {}
}
export function observeResponse(response, sink = console) {
 securityEvent(response.status,sink);
 return response;
}
