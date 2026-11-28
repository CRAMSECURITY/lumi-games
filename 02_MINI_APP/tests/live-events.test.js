import test from 'node:test';
import assert from 'node:assert/strict';
import {events,upcoming} from '../public/live-events.js';
test('curated events ordered and expired hidden',()=>{assert.equal(upcoming(events,'2026-11-28').length,3);assert.equal(upcoming(events,'2026-12-08').length,0);assert.equal(upcoming(events,'2026-12-01')[0].id,'founders-mixed-2026');});
test('city and category filters',()=>{assert.equal(upcoming(events,'2026-11-28','FRANKFURT','startup').length,1);assert.equal(upcoming(events,'2026-11-28','Berlin').length,0);});
test('unsafe links, invalid dates and duplicate IDs rejected',()=>{let e=events[0];assert.equal(upcoming([e,e,{...e,id:'x',url:'javascript:alert(1)'},{...e,id:'y',url:'https://evil.example'},{...e,id:'z',date:'2026-11-31'}],'2026-11-28').length,1);});
