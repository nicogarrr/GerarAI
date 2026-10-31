/**
 * Guard del fichero 720 y de los bloqueos del IRPF (components/taxes/
 * FilingSections.tsx): ningún «no disponible» sin explicación y ninguna descarga
 * que prometa una validación futura.
 *
 * Antes:
 *  - «No disponible para este ejercicio.» / «mapeo no verificado para este
 *    ejercicio»: estados sin decir qué falta ni qué haría falta.
 *  - Botón DESHABILITADO con «Descarga pendiente de validación» y «la descarga
 *    se habilitará cuando el generador supere la revisión de veracidad»: el
 *    contenido del fichero YA venía del backend (`file720.content`, ISO-8859-1)
 *    y la UI lo bloqueaba prometiendo un trabajo futuro.
 *  - «Pendiente: introduce el tipo medio efectivo…»: un estado con nombre de
 *    cola en algo que es una acción del usuario, no un proceso en curso.
 *
 * Ejecutar: node --experimental-strip-types --test scripts/taxes-filing-definitive-state-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const src = readFileSync('components/taxes/FilingSections.tsx', 'utf8');
// Las cadenas visibles viven en el diccionario i18n (carril C); el
// componente las referencia por clave. El guard verifica ambos extremos.
const esTaxes = JSON.parse(readFileSync('lib/i18n/messages/es/taxes.json', 'utf8'));

describe('Impuestos: casillas y fichero 720 sin estados intermedios', () => {
  it('nada de copy viejo de "no disponible"', () => {
    for (const banned of [
      'No disponible para este ejercicio',
      'mapeo no verificado para este ejercicio',
      'Descarga pendiente de validación',
      'se habilitará cuando el generador supere la revisión de veracidad',
      'Pendiente: introduce el tipo medio efectivo',
    ]) {
      assert.ok(!src.includes(banned), `prohibido: "${banned}"`);
    }
  });

  it('el bloqueo del IRPF muestra el motivo del backend y, si falta, qué se necesita', () => {
    assert.match(
      src,
      /typeof filing\.reason === 'string' && filing\.reason\s*\?\s*(?:humanizeTaxText\()?filing\.reason/,
      'el reason real del backend tiene prioridad',
    );
    // El texto de reserva (cuando el backend no da reason) dice qué haría falta.
    assert.match(src, /taxes\.filing\.fallbackReason/);
    assert.match(esTaxes.filing.fallbackReason, /cartera use EUR como divisa base y que el ejercicio tenga su mapeo verificado/);
    assert.match(esTaxes.filing.fallbackReason, /no ha devuelto el motivo del bloqueo/);
  });

  it('las casillas sin mapeo dicen qué haría falta, sin prometer publicación', () => {
    assert.match(src, /typeof casillas\.unavailable_reason === 'string'/);
    assert.match(src, /taxes\.filing\.fallbackBoxes/);
    assert.match(esTaxes.filing.fallbackBoxes, /solo se publican para ejercicios cuyo mapeo está verificado contra la orden ministerial/);
    assert.match(esTaxes.filing.fallbackBoxes, /haría falta verificar ese mapeo antes de darlos por buenos/);
  });

  it('el 0588 sin tipo medio efectivo es una acción del usuario, no una cola', () => {
    assert.match(src, /taxes\.filing\.row0588Pending/);
    assert.match(esTaxes.filing.row0588Pending, /Falta el tipo medio efectivo: introduce el TME de la base liquidable del ahorro de tu borrador/);
    assert.match(src, /dt\.status === 'pendiente_tme'/);
  });

  it('la descarga del 720 entrega el contenido real del generador', () => {
    assert.match(src, /function downloadFile720\(content: string, fileName: string\)/);
    // ISO-8859-1: cada carácter es un byte (charCodeAt & 0xff), no UTF-8.
    assert.match(src, /content\.charCodeAt\(index\) & 0xff/);
    assert.match(src, /type: 'application\/octet-stream'/);
    // El botón usa el contenido que llega, no un contador.
    assert.match(src, /const content720 =\s*typeof file720\?\.content === 'string'/);
    assert.match(src, /onClick=\{\(\) => downloadFile720\(content720, file720Name\)\}/);
    assert.match(src, /taxes\.modelo720\.download/);
    assert.equal(esTaxes.modelo720.download, 'Descargar borrador del 720');
    // Y sin contenido se declara una lectura fallida, no un fichero en espera.
    assert.match(src, /taxes\.modelo720\.noContent/);
    assert.match(esTaxes.modelo720.noContent, /es una lectura fallida, no un fichero esperando permiso/);
  });

  it('el borrador se declara ayuda de cómputo y se muestran las notas del generador', () => {
    assert.match(src, /taxes\.modelo720\.fileNote/);
    assert.match(esTaxes.modelo720.fileNote, /Es el contenido real que produce el generador, no una estimación/);
    assert.match(esTaxes.modelo720.fileNote, /es una ayuda de cómputo y no un fichero oficial listo para presentar/);
    assert.match(src, /Array\.isArray\(file720\.notas\)/);
    assert.match(src, /taxes\.modelo720\.reviewTitle/);
    assert.equal(esTaxes.modelo720.reviewTitle, 'Lo que hay que revisar antes de usarlo');
  });

  it('el 720 no disponible muestra el motivo real del generador', () => {
    assert.match(src, /typeof file720\.reason === 'string' && file720\.reason/);
    assert.ok(!src.includes("Fichero no disponible: {String(file720.reason"), 'sin fallback "faltan datos"');
  });
});