export const catalog = Object.freeze([
 ['ffm-garden','Frankfurt','date','Palmengarten','Ботанический сад для прогулки вдвоём.','https://frankfurt.de/themen/umwelt-und-gruen/orte/ausflugsziele/palmengarten'],
 ['ffm-design','Frankfurt','culture','Museum Angewandte Kunst','Музей дизайна и прикладного искусства.','https://frankfurt.de/themen/kultur/museen-und-kunst/museen-a-bis-z/museum-angewandte-kunst'],
 ['ffm-main','Frankfurt','date','Museumsufer','Прогулка вдоль Майна и музейная набережная.','https://www.visitfrankfurt.travel/en/experience/attractions'],
 ['ber-market','Berlin','food','Markthalle Neun','Гастрономический рынок.','https://www.visitberlin.de/de/markthallen'],
 ['ber-gallery','Berlin','culture','Berlinische Galerie','Современное искусство.','https://berlinischegalerie.de/'],
 ['ber-garden','Berlin','date','Botanischer Garten','Ботанический сад для неспешной прогулки.','https://www.berlin.de/tourismus/parks-und-gaerten/3560404-1740419-botanischer-garten.html']
].map(([id,city,kind,name,description,url])=>Object.freeze({id,city,kind,name,description,url})));
export function selectPlaces({city='',kind='',onlySaved=false,saved=new Set()}={}) {
 return catalog.filter(p=>(!city||p.city===city)&&(!kind||p.kind===kind)&&(!onlySaved||saved.has(p.id)));
}
export function mountCity(root){
 if(!root)return;
 const city=root.querySelector('[data-city-filter]'),kind=root.querySelector('[data-kind-filter]'),only=root.querySelector('[data-only-saved]'),list=root.querySelector('[data-city-list]');
 // Session-only: no account identifiers, persistent storage, or geolocation.
 const saved=new Set();
 function render(){list.replaceChildren();const results=selectPlaces({city:city.value,kind:kind.value,onlySaved:only.checked,saved});
 for(const p of results){const card=document.createElement('article');card.className='places-item';const meta=document.createElement('small');meta.textContent=p.city.toUpperCase()+' / CITY GUIDE';const h=document.createElement('h3');h.textContent=p.name;const d=document.createElement('p');d.textContent=p.description;const a=document.createElement('a');a.href=p.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Источник ↗';const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=saved.has(p.id)?'♥ В избранном':'♡ Сохранить';b.setAttribute('aria-pressed',String(saved.has(p.id)));b.addEventListener('click',()=>{saved.has(p.id)?saved.delete(p.id):saved.add(p.id);if(only.checked){render();only.focus()}else{b.textContent=saved.has(p.id)?'♥ В избранном':'♡ Сохранить';b.setAttribute('aria-pressed',String(saved.has(p.id)))}});card.append(meta,h,d,a,b);list.append(card)}
 if(!results.length){const p=document.createElement('p');p.textContent='Нет мест по этим фильтрам.';list.append(p)}}
 for(const control of [city,kind,only])control.addEventListener('change',render);render();
}
if(typeof document!=='undefined')mountCity(document.querySelector('[data-city-discovery]'));
