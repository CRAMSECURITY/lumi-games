import test from 'node:test';
import assert from 'node:assert/strict';
import {catalog,selectPlaces} from '../public/city-discovery.js';
test('curated city discovery: unique IDs, HTTPS links, city and category intersection, favorites',()=>{
 assert.equal(catalog.length,6);assert.equal(new Set(catalog.map(p=>p.id)).size,6);
 assert.ok(catalog.every(p=>new URL(p.url).protocol==='https:'));
 assert.equal(selectPlaces({city:'Frankfurt'}).length,3);
 assert.deepEqual(selectPlaces({city:'Berlin',kind:'food'}).map(p=>p.id),['ber-market']);
 assert.equal(selectPlaces({city:'unknown'}).length,0);
 assert.equal(selectPlaces({onlySaved:true,saved:new Set(['ffm-main'])})[0].id,'ffm-main');
});
