import test from 'node:test';
import assert from 'node:assert/strict';
import {offers,selectOffers} from '../public/city-partners.js';
test('partner offers default empty and only confirmed active safe records appear',()=>{
 const now=Date.parse('2026-11-28T12:00:00Z');
 const o={id:'test',name:'Test',terms:'Test terms',city:'Berlin',status:'confirmed',start:'2026-11-28T00:00:00Z',end:'2026-11-29T00:00:00Z',url:'https://example.com/terms'};
 assert.deepEqual(selectOffers(offers,{now}),[]);
 assert.deepEqual(selectOffers([o],{now,city:'Berlin'}),[o]);
 for(const changes of [{status:'draft'},{end:o.start},{start:o.end},{url:'javascript:alert(1)'},{url:'https://user:pass@example.com'},{terms:''},{end:'invalid'}])assert.deepEqual(selectOffers([{...o,...changes}],{now}),[]);
 assert.deepEqual(selectOffers([o],{now,city:'Frankfurt'}),[]);
});
