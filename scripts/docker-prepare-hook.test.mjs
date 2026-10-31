import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
test('Docker dependency stage provides the prepare hook before npm ci',()=>{
 const docker=readFileSync('Dockerfile','utf8');
 const hook=docker.indexOf('COPY scripts/install-hooks.mjs ./scripts/install-hooks.mjs');
 assert.ok(hook>0);
 assert.ok(hook<docker.indexOf('RUN npm ci'));
 const pkg=JSON.parse(readFileSync('package.json','utf8'));
 assert.equal(pkg.scripts.prepare,'node scripts/install-hooks.mjs');
});
