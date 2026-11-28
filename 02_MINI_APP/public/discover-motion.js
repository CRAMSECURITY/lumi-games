(()=>{'use strict';
const root=document.getElementById('places-dialog');if(!root)return;
const motion=window.matchMedia('(prefers-reduced-motion: reduce)');
const selector='.places-item,.places-business,.business-identity > summary';
const clamp=(v,min,max)=>Math.min(max,Math.max(min,v));
let active=null,rect=null,latest=null,frame=0,down=null,suppressed=null;
const cardFor=e=>e.target instanceof Element?e.target.closest(selector):null;
const clear=()=>{if(frame)cancelAnimationFrame(frame);frame=0;latest=null;if(active){active.classList.remove('is-discover-tilting');for(const k of ['--card-rx','--card-ry','--card-x','--card-y'])active.style.removeProperty(k)}active=null;rect=null};
function move(e){if(motion.matches||document.hidden||!root.open||e.isPrimary===false)return;const card=cardFor(e);if(!card||!root.contains(card)){clear();return}if(e.pointerType==='touch'&&(!down||down.id!==e.pointerId||down.card!==card))return;if(down&&down.id===e.pointerId&&Math.hypot(e.clientX-down.x,e.clientY-down.y)>9)down.dragged=true;if(active!==card){clear();active=card;rect=card.getBoundingClientRect();if(!rect.width||!rect.height){clear();return}card.classList.add('is-discover-tilting')}latest={x:e.clientX,y:e.clientY};if(frame)return;frame=requestAnimationFrame(()=>{frame=0;if(!active||!latest||!active.isConnected||!root.open){clear();return}const x=clamp((latest.x-rect.left)/rect.width,0,1),y=clamp((latest.y-rect.top)/rect.height,0,1);active.style.setProperty('--card-rx',`${((.5-y)*16).toFixed(2)}deg`);active.style.setProperty('--card-ry',`${((x-.5)*16).toFixed(2)}deg`);active.style.setProperty('--card-x',`${x*100}%`);active.style.setProperty('--card-y',`${y*100}%`)})}
root.addEventListener('pointerdown',e=>{if(e.isPrimary===false)return;suppressed=null;const card=cardFor(e);if(!card)return;down={id:e.pointerId,x:e.clientX,y:e.clientY,card,dragged:false};move(e)},{passive:true});
root.addEventListener('pointermove',move,{passive:true});
function release(e){if(down&&down.id===e.pointerId){if(down.dragged||Math.hypot(e.clientX-down.x,e.clientY-down.y)>9)suppressed={card:down.card,until:performance.now()+450};down=null}clear()}
window.addEventListener('pointerup',release,{passive:true});window.addEventListener('pointercancel',e=>{if(down?.id===e.pointerId)down=null;clear()},{passive:true});root.addEventListener('pointerleave',clear,{passive:true});
root.addEventListener('click',e=>{if(e.detail!==0&&suppressed&&performance.now()<suppressed.until&&cardFor(e)===suppressed.card){e.preventDefault();e.stopImmediatePropagation();suppressed=null}},true);
root.addEventListener('scroll',clear,{passive:true});root.addEventListener('close',()=>{down=null;suppressed=null;clear()});document.addEventListener('visibilitychange',()=>{if(document.hidden){down=null;clear()}});motion.addEventListener?.('change',clear);
})();
