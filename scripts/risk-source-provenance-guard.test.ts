import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097 explicit extension required.
import {ownershipLimitations} from '../lib/research/ownership-display.ts';
test('risk never attributes a missing source to Postgres',()=>{
 const src=readFileSync('components/risk/RiskDashboardView.tsx','utf8');
 assert.match(src,/rawSource === null \? 'Fuente interna' : rawSource === 'CavaAI Postgres' \? 'Base de datos de GerarAI'/);
});
test('13F limitations share one helper for list/text and preserve unknown warnings',()=>{
 assert.equal(existsSync('lib/limitation-labels.ts'),false);
 assert.equal(ownershipLimitations(['Amendments are separate immutable filings','SIN_DATOS']), 'Las enmiendas son declaraciones inmutables independientes. N/D');
 assert.equal(ownershipLimitations(null),'');
 assert.equal(ownershipLimitations('Nueva advertencia'),'Nueva advertencia');
});
