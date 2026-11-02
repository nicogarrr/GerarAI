import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { backendMessage } from '@/lib/research/backend-error-es';

// paper_trading.py: un valor que no es un número («abc») ya no se anuncia
// como «fuera de la precisión persistida». La frase del backend se lee del
// propio fichero para que la traducción no se quede atrás si cambia.
const BACKEND = readFileSync(path.resolve(__dirname, '../../../data-engine/app/schemas/paper_trading.py'), 'utf8');

describe('paper trading: a non-number reads as such in English', () => {
  it('the backend still sends the sentence', () => {
    expect(BACKEND).toContain('"El valor debe ser un número"');
  });

  it('translates it with English selected and leaves Spanish untouched', () => {
    expect(backendMessage('Value error, El valor debe ser un número', 'en')).toBe('The value must be a number.');
    expect(backendMessage('El valor debe ser un número', 'es')).toBe('El valor debe ser un número');
  });
});
