import test from 'node:test';
import assert from 'node:assert/strict';
import {buildPlan} from '../public/date-planner.js';
const now=new Date('2026-11-28T10:00:00Z');
const input={placeId:'ffm-garden',date:'2026-11-29',time:'15:00'};
test('planner creates private proposal using catalog and explicit timezone',()=>{const p=buildPlan(input,now);assert.equal(p.place.id,input.placeId);assert.match(p.text,/Europe\/Berlin/);assert.match(p.text,/не бронирование/);});
test('planner rejects invalid dates, unknown places, past times and ambiguous DST',()=>{for(const patch of [{date:'2026-11-31'},{date:'2026-11-28',time:'10:30'},{placeId:'fake'},{time:'24:00'},{date:'2027-03-28',time:'02:30'},{date:'2027-10-31',time:'02:30'}])assert.equal(buildPlan({...input,...patch},now),null);});
