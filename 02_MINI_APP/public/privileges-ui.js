(()=>{
 const load=document.getElementById('privilege-load'),list=document.getElementById('privilege-list'),status=document.getElementById('privilege-status');if(!load||!list||!status)return;
 let generation=0,busy=false;
 const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
 async function run(fn){if(busy)return;busy=true;const g=generation;status.textContent='Загрузка…';try{await fn(g);}catch(e){if(g===generation)status.textContent=e.message||'Ошибка соединения';}finally{busy=false;}}
 async function render(g){const d=await window.lumiPrivilegeApi('list');if(g!==generation)return;list.replaceChildren();for(const o of d.offers){const card=node('article','');card.className='places-item';card.append(node('h3',o.title),node('p',o.city+' · '+o.terms),node('small','До '+new Date(o.ends_at*1000).toLocaleString()));if(o.redeemed_at)card.append(node('p','Использовано'));else if(o.code)card.append(node('p','Покажи код только партнёру: '+o.code));else{const b=node('button','ПОЛУЧИТЬ КОД ↗');b.type='button';b.className='secondary';b.onclick=()=>run(async g=>{if(!window.confirm('Получить персональный код?')){status.textContent='Без изменений';return;}await window.lumiPrivilegeApi('claim',{id:o.id,consent:true});await render(g);});card.append(b);}list.append(card);}status.textContent=d.offers.length?'Предложений: '+d.offers.length:'Активных привилегий пока нет.';}
 load.onclick=()=>run(render);document.getElementById('places-dialog').addEventListener('close',()=>{generation++;list.replaceChildren();status.textContent='';});
})();
