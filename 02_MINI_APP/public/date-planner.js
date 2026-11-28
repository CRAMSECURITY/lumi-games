import {catalog} from './city-discovery.js';
export function buildPlan({placeId='',date='',time=''}={},now=new Date()){
 const place=catalog.find(p=>p.id===placeId);
 if(!place||!/^\d{4}-\d{2}-\d{2}$/.test(date)||!/^([01]\d|2[0-3]):[0-5]\d$/.test(time))return null;
 const [y,m,d]=date.split('-').map(Number);
 const day=new Date(Date.UTC(y,m-1,d));
 if(day.getUTCFullYear()!==y||day.getUTCMonth()!==m-1||day.getUTCDate()!==d)return null;
 // Both pilot cities use Europe/Berlin; compare wall-clock values, not device timezone.
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Berlin',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(now).map(p=>[p.type,p.value]));
 if(`${date}T${time}`<=`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`)return null;
 // Avoid ambiguous/nonexistent DST times: the plan is a wall-clock proposal, not a reservation.
 if(time>='02:00'&&time<'03:00'&&day.getUTCDay()===0&&d>=25&&(m===3||m===10))return null;
 return {place,date,time,text:`Предложение встречи в LUMI\n${place.name} · ${place.city}\n${date}, ${time} (Europe/Berlin)\n${place.url}\nПодходит? Подтверди в ответном сообщении. Это не бронирование.`};
}
export function mountPlanner(root){
 if(!root)return;
 const form=root.querySelector('form'),city=root.querySelector('[data-plan-city]'),place=root.querySelector('[data-plan-place]'),date=root.querySelector('[data-plan-date]'),time=root.querySelector('[data-plan-time]'),out=root.querySelector('[data-plan-output]'),copy=root.querySelector('[data-plan-copy]'),status=root.querySelector('[data-plan-status]');
 let plan=null;
 function clear(){plan=null;out.value='';copy.disabled=true;status.textContent='';}
 function places(){place.replaceChildren();for(const p of catalog.filter(p=>p.city===city.value)){const opt=document.createElement('option');opt.value=p.id;opt.textContent=p.name;place.append(opt);}clear();}
 city.addEventListener('change',places);form.addEventListener('input',clear);form.addEventListener('change',clear);
 form.addEventListener('submit',e=>{e.preventDefault();clear();plan=buildPlan({placeId:place.value,date:date.value,time:time.value});if(!plan){status.textContent='Выбери корректную будущую дату и время по местному времени города.';return;}out.value=plan.text;copy.disabled=false;status.textContent='Черновик готов. Отправь его самостоятельно и дождись ответа.';});
 copy.addEventListener('click',async()=>{if(!plan)return;const current=plan;try{await navigator.clipboard.writeText(current.text);if(plan===current)status.textContent='Скопировано. Теперь отправь приглашение в личном чате.';}catch{if(plan===current){out.focus();out.select();status.textContent='Скопируй выделенный текст вручную.';}}});
 function reset(){form.reset();places();}
 root.addEventListener('toggle',()=>{if(!root.open)reset();});root.closest('dialog')?.addEventListener('close',reset);places();
}
if(typeof document!=='undefined')mountPlanner(document.querySelector('[data-date-planner]'));
