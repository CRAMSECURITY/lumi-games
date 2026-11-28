(()=>{
 const $=id=>document.getElementById(id),panel=$('studio-panel'),list=$('studio-list'),status=$('studio-status'),form=$('studio-form'),redeem=$('studio-redeem');
 if(!panel)return;let busy=false,generation=0;
 const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
 async function run(fn){if(busy)return;busy=true;const g=generation;try{await fn(g);}catch(e){if(g===generation)status.textContent=e.message||'Ошибка';}finally{busy=false;}}
 async function render(g){const d=await window.lumiPrivilegeApi('studio-list');if(g!==generation)return;panel.hidden=false;list.replaceChildren();for(const o of d.offers){const card=node('article','');card.className='places-item';card.append(node('h3',o.title),node('p',o.city+' · '+o.terms),node('p',o.enabled?'Опубликовано':'Не опубликовано'),node('p',`Выдано: ${o.issued} · Погашено: ${o.redeemed}`));if(o.enabled){const b=node('button','Остановить предложение');b.type='button';b.className='secondary';b.onclick=()=>run(async g=>{if(!confirm('Остановить предложение? Неиспользованные коды станут недоступны.'))return;await window.lumiPrivilegeApi('studio-pause',{id:o.id,consent:true});await render(g);});card.append(b);}list.append(card);}status.textContent='Предложений: '+d.offers.length;}
 $('studio-load').onclick=()=>run(render);
 form.onsubmit=e=>{e.preventDefault();const f=new FormData(form);run(async g=>{await window.lumiPrivilegeApi('studio-create',{title:f.get('title'),city:f.get('city'),terms:f.get('terms'),starts_at:Math.floor(new Date(f.get('start')).getTime()/1000),ends_at:Math.floor(new Date(f.get('end')).getTime()/1000),consent:f.has('consent')});if(g===generation)form.reset();await render(g);});};
 redeem.onsubmit=e=>{e.preventDefault();const code=new FormData(redeem).get('code');if(!confirm('Подтвердить использование кода?'))return;run(async g=>{await window.lumiPrivilegeApi('redeem',{code,consent:true});if(g===generation)redeem.reset();await render(g);if(g===generation)status.textContent='Код погашен.';});};
 $('places-dialog').addEventListener('close',()=>{generation++;panel.hidden=true;list.replaceChildren();form.reset();redeem.reset();status.textContent='';});
})();
