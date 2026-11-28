(()=>{'use strict';
// Observe only continuously animated card surfaces; no polling or scroll handler.
const cards=document.querySelectorAll('.home-float-stage,.arena-create-stage,#places-dialog .places-business');
const sync=()=>document.documentElement.classList.toggle('lumi-background',document.hidden);
sync();document.addEventListener('visibilitychange',sync);
if(typeof IntersectionObserver!=='function')return;
const observer=new IntersectionObserver(entries=>{for(const entry of entries)entry.target.classList.toggle('lumi-offscreen',!entry.isIntersecting)},{rootMargin:'32px'});
for(const card of cards)observer.observe(card);
})();
