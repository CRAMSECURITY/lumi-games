(()=>{'use strict';
const back=window.Telegram?.WebApp?.BackButton;
if(typeof back?.onClick!=='function'||typeof back.show!=='function'||typeof back.hide!=='function'||typeof MutationObserver!=='function')return;
const home=document.getElementById('tab-home'),welcome=document.getElementById('welcome');
if(!home||!welcome)return;
const stack=[];
function reconcile(){
 for(let i=stack.length-1;i>=0;i--)if(!stack[i].open||!stack[i].isConnected)stack.splice(i,1);
 for(const dialog of document.querySelectorAll('dialog[open]'))if(!stack.includes(dialog))stack.push(dialog);
}
let visible;
function sync(){reconcile();const next=welcome.hidden&&(stack.length>0||home.getAttribute('aria-current')!=='page');if(next===visible)return;try{next?back.show():back.hide();visible=next}catch{}}
function goBack(){reconcile();if(!welcome.hidden)return;const dialog=stack[stack.length-1];if(dialog){dialog.close();sync();return}if(home.getAttribute('aria-current')!=='page')home.click();sync()}
try{back.onClick(goBack)}catch{return}
const observer=new MutationObserver(records=>{for(const r of records){const el=r.target;if(r.attributeName==='open'&&el.tagName==='DIALOG'){const i=stack.indexOf(el);if(i>=0)stack.splice(i,1);if(el.open&&el.isConnected)stack.push(el)}}sync()});
observer.observe(document.body,{subtree:true,attributes:true,attributeFilter:['open','hidden','aria-current'],childList:true});sync();
})();
