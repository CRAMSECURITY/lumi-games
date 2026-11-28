(()=>{'use strict';
// Only completed, trusted activations in sections without existing haptic handlers.
const selector='#places-dialog button,#places-dialog summary,#places-dialog a[href],.tabs button,#home-places';
let last=-Infinity;
document.addEventListener('click',event=>{
  if(!event.isTrusted||event.defaultPrevented||document.hidden||event.detail===0)return;
  const target=event.target?.closest?.(selector);
  if(!target||target.closest('[disabled],[aria-disabled="true"],[inert]'))return;
  if(window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches)return;
  const now=performance.now();if(now-last<100)return;
  const feedback=window.Telegram?.WebApp?.HapticFeedback;
  if(typeof feedback?.selectionChanged!=='function')return;
  last=now;try{feedback.selectionChanged()}catch{}
});
})();
