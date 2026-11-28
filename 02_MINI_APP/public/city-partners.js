// Editorially managed offers: empty until a signed partner supplies confirmed terms.
export const offers = Object.freeze([]);
export function selectOffers(records=offers, {city='',now=Date.now()}={}) {
 return records.filter(o=>{
  if(!o || o.status!=='confirmed' || !o.id || !o.name || !o.terms || !o.city || (city && o.city!==city))return false;
  const start=Date.parse(o.start),end=Date.parse(o.end);
  if(!Number.isFinite(now)||!Number.isFinite(start)||!Number.isFinite(end)||start>now||end<=now)return false;
  try {const u=new URL(o.url);return u.protocol==='https:' && !u.username && !u.password;}catch{return false;}
 });
}
export function mountPartners(root){
 if(!root)return;
 const city=root.querySelector('[data-partner-city]'),list=root.querySelector('[data-partner-list]');
 function render(){list.replaceChildren();const active=selectOffers(offers,{city:city.value});
 if(!active.length){const p=document.createElement('p');p.className='note';p.textContent='Подтверждённых предложений пока нет. Здесь появятся условия от официальных партнёров LUMI.';list.append(p);return;}
 for(const o of active){const card=document.createElement('article');card.className='places-item';const meta=document.createElement('small');meta.textContent=o.city+' / PARTNER OFFER';const h=document.createElement('h3');h.textContent=o.name;const p=document.createElement('p');p.textContent=o.terms;const date=document.createElement('p');date.textContent='Действует до '+new Date(o.end).toLocaleString('ru-RU');const a=document.createElement('a');a.href=o.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Условия у партнёра ↗';card.append(meta,h,p,date,a);list.append(card);}}
 city.addEventListener('change',render);root.addEventListener('toggle',()=>{if(root.open)render()});render();
}
if(typeof document!=='undefined')mountPartners(document.querySelector('[data-city-partners]'));
