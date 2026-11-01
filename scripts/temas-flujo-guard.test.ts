/**
 * Guard veracidad: el flujo de dinero dentro de /temas nunca inventa importes.
 *
 * Decisión de Nico (2026-10-20): el flujo va dentro del detalle de cada tema,
 * no en una página nueva. Verde/teal = reportado con fuente oficial; ámbar =
 * estimación de terceros atribuida; sin reparto público verificable → N/D.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/temas-flujo-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pagina = readFileSync('app/(root)/temas/page.tsx', 'utf8');
const flujo = readFileSync('app/(root)/temas/_components/ThemeFlow.tsx', 'utf8');
const acciones = readFileSync('lib/actions/money-flows.actions.ts', 'utf8');
// Textos en español: solo la sección `flow` del diccionario (el componente usa t()).
const flujoEs = JSON.stringify(JSON.parse(readFileSync('lib/i18n/messages/es/themes.json', 'utf8')).flow);
const flujoTexto = `${flujo}\n${flujoEs}`;

describe('Flujo de dinero dentro del detalle de cada tema', () => {
  it('la página lo integra en la tarjeta del tema, no en una ruta nueva', () => {
    assert.ok(pagina.includes('<ThemeFlow flow={flow} holdings={holdings} />'));
    assert.ok(!pagina.includes("href=\"/flujos"), 'sin enlace a una página /flujos aparte');
  });

  it('flujo declarado por el backend pero no entregado: N/D visible con causa, nunca ausencia silenciosa', () => {
    assert.ok(pagina.includes('failedFlowIds'), 'la página registra los flujos declarados no entregados');
    assert.ok(pagina.includes('failedFlowIds.has(theme.id)'), 'la tarjeta recibe el fallo de SU tema');
    assert.ok(pagina.includes('<ThemeFlowUnavailable />'), 'la tarjeta monta el estado N/D');
    assert.match(flujoTexto, /Flujo de dinero N\/D: el backend declara este flujo pero no lo ha devuelto/);
    assert.match(flujoTexto, /Sin importes en lugar de inventarlos/);
    assert.ok(flujo.includes("t('themes.flow.unavailable')"));
  });

  it('degrada en silencio si el endpoint no existe (no rompe /temas)', () => {
    assert.match(acciones, /catch \{\s*return \[\];/);
    assert.match(acciones, /catch \{\s*return null;/);
    assert.ok(pagina.includes('flowsById.get(theme.id) ?? null'));
  });

  it('la estimación de terceros se distingue visualmente del dato reportado', () => {
    assert.ok(flujo.includes("kind === 'estimacion_terceros'"));
    assert.ok(flujo.includes('text-amber-300'), 'ámbar para terceros');
    assert.ok(flujoTexto.includes('Quién gasta · reportado'));
    assert.ok(flujoTexto.includes('estimación de terceros'));
  });

  it('los importes respetan la divisa de la fila: USD en es-ES con US$ (Nico 29-oct-2026)', () => {
    const formatos = readFileSync('lib/market/flows.ts', 'utf8');
    assert.ok(!formatos.includes("toLocaleString('en-US'"), 'USD se formatea en es-ES');
    assert.ok(!formatos.includes('B$'), 'nada de «B$» ambiguo');
    assert.match(formatos, /unit = 'USD'/, 'la divisa llega por parámetro');
    assert.match(flujo, /formatFlowAmount\(spender\.amount, spender\.unit[,)]/);
    assert.match(flujo, /formatFlowAmount\(destination\.amount, destination\.unit[,)]/);
    assert.match(flujo, /formatFlowAmount\(supplier\.amount, supplier\.unit[,)]/);
  });

  it('sin reparto verificable no hay importe: solo razón declarada', () => {
    assert.match(flujo, /formatFlowAmount\(supplier\.amount, supplier\.unit[,)]/);
    assert.match(flujo, /supplier\.amount !== null \? \(/);
    assert.ok(flujoTexto.includes('Tu exposición'), 'sección de exposición presente');
    assert.ok(flujo.includes('holdings.unavailable'), 'exposición oculta si el dato no llegó');
  });
});
