import { describe, expect, it } from 'vitest';

import { backendMessage, spanishBackendMessage } from '@/lib/research/backend-error-es';

describe('known Spanish engine messages are shown in English with English selected', () => {
  it('translates fixed route and validation messages, keeping quoted values', () => {
    expect(backendMessage('Ya existe una cartera con este nombre para el usuario.', 'en')).toBe('A portfolio with this name already exists.');
    expect(backendMessage('El archivo supera el máximo de 10 MB para importación', 'en')).toBe('The file exceeds the 10 MB import limit.');
    expect(backendMessage("Divisa no reconocida: 'EURO' (se esperaba un código como EUR, USD o GBp)", 'en'))
      .toBe("Unrecognised currency: 'EURO' (expected a code such as EUR, USD or GBp)");
    expect(backendMessage('La fecha de operación no puede ser futura (2027-01-02)', 'en')).toBe('The trade date cannot be in the future (2027-01-02).');
    expect(backendMessage('Value error, El precio de la alerta debe ser mayor que 0', 'en')).toBe('The alert price must be greater than 0.');
    expect(backendMessage('KO: la divisa no coincide con el instrumento', 'en')).toBe('KO: the currency does not match the instrument.');
    expect(backendMessage('rango máximo: 366 días', 'en')).toBe('Maximum range: 366 days.');
  });

  it('leaves unknown Spanish text and the Spanish interface untouched', () => {
    expect(backendMessage('La colección no está vacía', 'en')).toBe('La colección no está vacía');
    const raw = 'Ya existe una cartera con este nombre para el usuario.';
    expect(backendMessage(raw, 'es')).toBe(spanishBackendMessage(raw));
    expect(backendMessage(raw, 'es')).toBe(raw);
  });
});
