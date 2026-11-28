(()=>{'use strict';
const dialog=document.getElementById('places-dialog');if(!dialog)return;
const routes={live:['ecosystem-live',null],network:['business-identity','business-discover'],join:['ecosystem-organizer','registration-mine'],create:['ecosystem-organizer','organizer-form'],city:['city-discovery',null],moments:['city-moments',null]};
for(const button of dialog.querySelectorAll('[data-ecosystem]'))button.addEventListener('click',()=>{
const route=routes[button.dataset.ecosystem];if(!Object.hasOwn(routes,button.dataset.ecosystem))return;
const section=document.getElementById(route[0]);if(!section)return;section.open=true;
const target=route[1]?document.getElementById(route[1]):section.querySelector('summary');
if(!target)return;const focus=target.tagName==='FORM'?target.querySelector('input'):target;
focus?.focus({preventScroll:true});target.scrollIntoView({block:'start',behavior:'instant'});
});
})();
