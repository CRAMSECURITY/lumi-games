import test from 'node:test';
import assert from 'node:assert/strict';
import {recommend} from '../public/city-match.js';
test('city match prioritizes shared interests and excludes other cities',()=>{
 const r=recommend({city:'Frankfurt',first:'walk',second:'walk'});assert.equal(r.length,2);assert.ok(r.every(x=>x.score===2&&x.place.city==='Frankfurt'));
 const mixed=recommend({city:'Berlin',first:'meal',second:'art'});assert.equal(mixed.length,2);assert.ok(mixed.every(x=>x.score===1));
});
test('city match has no fabricated fallback and rejects unknown input',()=>{
 assert.deepEqual(recommend({city:'Frankfurt',first:'meal',second:'meal'}),[]);
 assert.deepEqual(recommend({city:'unknown',first:'walk',second:'walk'}),[]);
 assert.deepEqual(recommend({city:'Berlin',first:'__proto__',second:'walk'}),[]);
});
