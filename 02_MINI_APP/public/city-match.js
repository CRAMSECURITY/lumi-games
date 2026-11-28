import {catalog} from './city-discovery.js';
const formats={walk:'date',meal:'food',art:'culture'};
export function recommend({city='',first='',second=''}={}){
 if(!['Frankfurt','Berlin'].includes(city)||!Object.hasOwn(formats,first)||!Object.hasOwn(formats,second))return [];
 return catalog.filter(p=>p.city===city).map(p=>({place:p,score:Number(p.kind===formats[first])+Number(p.kind===formats[second])})).filter(p=>p.score>0).sort((a,b)=>b.score-a.score);
}
export function mountMatch(root){
 if(!root)return;
 const form=root.querySelector('form'),city=root.querySelector('[data-match-city]'),first=root.querySelector('[data-match-first]'),second=root.querySelector('[data-match-second]'),list=root.querySelector('[data-match-results]');
 const clear=()=>list.replaceChildren();
 form.addEventListener('change',clear);
 form.addEventListener('submit',e=>{e.preventDefault();clear();const results=recommend({city:city.value,first:first.value,second:second.value});
 if(!results.length){const p=document.createElement('p');p.textContent='В подборке пока нет подходящих мест. Попробуй другой формат или город.';list.append(p);return;}
 for(const {place,score} of results){const card=document.createElement('article');card.className='places-item';const meta=document.createElement('small');meta.textContent=score===2?'ОБЩИЙ ИНТЕРЕС':'ОДИН ИЗ ИНТЕРЕСОВ';const h=document.createElement('h3');h.textContent=place.name;const d=document.createElement('p');d.textContent=place.description;const a=document.createElement('a');a.href=place.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Подробнее ↗';card.append(meta,h,d,a);list.append(card);}
 });
 root.addEventListener('toggle',()=>{if(!root.open){form.reset();clear();}});
 root.closest('dialog')?.addEventListener('close',()=>{form.reset();clear();});
}
if(typeof document!=='undefined')mountMatch(document.querySelector('[data-city-match]'));
