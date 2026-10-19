import assert from 'node:assert/strict';
// @ts-expect-error TS5097
import { debateErrorMessage } from '../lib/research/debate-error.ts';
assert.equal(debateErrorMessage(new Error('LLM gratuito agotado, vuelve más tarde')), 'LLM gratuito agotado, vuelve más tarde');
assert.equal(debateErrorMessage(new Error('El debate devolvió una respuesta no válida; vuelve más tarde')), 'El debate devolvió una respuesta no válida; vuelve más tarde');
const wrapped = Object.assign(new Error('fetch fallido'), { originalError: new DOMException('deadline', 'TimeoutError') });
assert.equal(debateErrorMessage(wrapped), 'El debate tardó demasiado; vuelve más tarde');
assert.equal(debateErrorMessage(new Error('secret provider https://private/?key=abc')), 'No se pudo generar el debate; reinténtalo.');
