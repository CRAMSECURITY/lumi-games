import test from 'node:test';
import assert from 'node:assert/strict';
import {collectMoments} from '../public/moments.js';
import {readFileSync} from 'node:fs';
test('moments merges only confirmed future personal plans in Berlin time',()=>{
 const now=new Date('2026-11-28T10:00:00Z');const p={id:'a',place_id:'ffm-garden',day:'2026-11-29',time:'12:00',state:'accepted'};const e={id:'b',joined:1,state:'approved',organizer_active:1,starts_at:Date.parse('2026-11-29T09:00:00Z')/1000,title:'Meet',city:'Berlin',venue:'Hall'};
 const plans=[p,{...p,id:'c',state:'pending'},{...p,id:'d',day:'2026-11-27'}];const events=[e,{...e,id:'f',joined:0},{...e,id:'g',state:'cancelled'},{...e,id:'h',organizer_active:0}];
 assert.deepEqual(collectMoments(plans,events,now).map(r=>[r.id,r.when]),[['event:b','2026-11-29 10:00'],['date:a','2026-11-29 12:00']]);assert.equal(collectMoments(plans,events,now,'date').length,1);
});
test('registration UI API allows all existing registration actions',()=>{const html=readFileSync(new URL('../public/index.html',import.meta.url),'utf8');for(const action of ['mine','list','join','leave'])assert.ok(html.includes(`'registration/${action}':['registration/${action}'`));});
