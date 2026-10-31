import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097 explicit extension required.
import {ownershipLimitations} from '../lib/research/ownership-display.ts';
test('risk no longer renders source labels, so it cannot misattribute one (#3527)',()=>{
 const src=readFileSync('components/risk/RiskDashboardView.tsx','utf8');
 // #3527: la UI no pinta etiquetas de fuente; sin etiqueta no cabe atribuir
 // una fuente ausente a Postgres. Si se reintroduce una etiqueta, debe
 // volver la ramificacion null / proveedor y este guard debe actualizarse.
 assert.doesNotMatch(src,/rawSource/);
 assert.doesNotMatch(src,/risk\.values\.sourceInternal|risk\.values\.sourceCava/);
});
test('13F limitations share one helper for list/text and preserve unknown warnings',()=>{
 assert.equal(existsSync('lib/limitation-labels.ts'),false);
 assert.equal(ownershipLimitations(['Amendments are separate immutable filings','SIN_DATOS']), 'Las enmiendas son declaraciones inmutables independientes. N/D');
 assert.equal(ownershipLimitations(null),'');
 assert.equal(ownershipLimitations('Nueva advertencia'),'Nueva advertencia');
});
