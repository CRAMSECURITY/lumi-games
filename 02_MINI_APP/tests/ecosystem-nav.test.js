import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const code=readFileSync(new URL('../public/ecosystem-nav.js',import.meta.url),'utf8');
test('ecosystem shortcuts open correct sections without sending requests or submitting forms',()=>{
const node=(tagName='BUTTON')=>({tagName,focus(){this.focused=true},scrollIntoView(){this.scrolled=true},click(){throw Error('unexpected automatic action')}});
const input=node('INPUT'), form=node('FORM');form.querySelector=()=>input;
const summary=node('SUMMARY'),live={querySelector:()=>summary},network={},organizer={},discover=node(),join=node();
const buttons=['live','network','join','create','__proto__','city','moments'].map(key=>({dataset:{ecosystem:key},addEventListener(_,fn){this.run=fn}}));
const city={querySelector:()=>node()},moments={querySelector:()=>node()};
const ids={'places-dialog':{querySelectorAll:()=>buttons},'ecosystem-live':live,'business-identity':network,'ecosystem-organizer':organizer,'business-discover':discover,'registration-mine':join,'organizer-form':form,'city-discovery':city,'city-moments':moments};
runInNewContext(code,{document:{getElementById:id=>ids[id]}});
buttons[0].run();assert.ok(live.open&&summary.focused&&summary.scrolled);
buttons[1].run();assert.ok(network.open&&discover.focused);
buttons[2].run();assert.ok(organizer.open&&join.focused);
buttons[3].run();assert.ok(input.focused&&form.scrolled);buttons[4].run();buttons[5].run();buttons[6].run();assert.ok(city.open&&moments.open);
});
