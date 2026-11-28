(()=>{'use strict';
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let active=null,moved=false,suppress=null,pending=0,latest=null,painted=null;
function clear(c){if(!c)return;c.classList.remove('tilting');for(const k of ['--rx','--ry','--px','--py'])c.style.removeProperty(k)}
function reset(c){if(latest?.c===c){cancelAnimationFrame(pending);pending=0;latest=null}clear(c);if(painted===c)painted=null}
function flush(){pending=0;const next=latest;latest=null;if(!next||reduced.matches||document.hidden)return;const {c,x:clientX,y:clientY}=next;const r=c.getBoundingClientRect();if(!r.width||!r.height)return;if(painted&&painted!==c)clear(painted);painted=c;const x=Math.max(0,Math.min(1,(clientX-r.left)/r.width)),y=Math.max(0,Math.min(1,(clientY-r.top)/r.height));c.classList.add('tilting');c.style.setProperty('--rx',`${(0.5-y)*22}deg`);c.style.setProperty('--ry',`${(x-0.5)*22}deg`);c.style.setProperty('--px',`${x*100}%`);c.style.setProperty('--py',`${y*100}%`)}
function tilt(c,e){if(reduced.matches||document.hidden)return;latest={c,x:e.clientX,y:e.clientY};if(!pending)pending=requestAnimationFrame(flush)}
document.addEventListener('pointerdown',e=>{const c=e.target.closest('.holo-card');if(!c||!e.isPrimary)return;active={c,id:e.pointerId,x:e.clientX,y:e.clientY};moved=false;tilt(c,e)});
document.addEventListener('pointermove',e=>{if(active&&active.id===e.pointerId){if(Math.hypot(e.clientX-active.x,e.clientY-active.y)>8)moved=true;tilt(active.c,e)}else if(!active&&e.pointerType==='mouse'){const c=e.target.closest('.holo-card');if(c)tilt(c,e)}});
function end(e){if(!active||active.id!==e.pointerId)return;if(moved)suppress={c:active.c,time:performance.now()};reset(active.c);active=null}
document.addEventListener('pointerup',end);document.addEventListener('pointercancel',end);
document.addEventListener('pointerout',e=>{const c=e.target.closest('.holo-card');if(c&&!c.contains(e.relatedTarget)&&active?.c!==c)reset(c)});
function stop(){if(latest)reset(latest.c);if(painted)reset(painted);active=null;moved=false}
document.addEventListener('visibilitychange',()=>{if(document.hidden)stop()});reduced.addEventListener?.('change',()=>{if(reduced.matches)stop()});
document.addEventListener('click',e=>{if(suppress&&performance.now()-suppress.time<450&&suppress.c.contains(e.target)){e.preventDefault();e.stopImmediatePropagation();suppress=null}},true);
})();
