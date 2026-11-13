import { describe, expect, it } from 'vitest';

import { backendMessage } from '@/lib/research/backend-error-es';

describe('mensajes locales de validación del frontend en inglés (Ajustes → Idioma = English)', () => {
  it('traduce los rechazos locales de alertas y del screener ad-hoc', () => {
    expect(backendMessage('Introduce un ticker válido', 'en')).toBe('Enter a valid ticker.');
    expect(backendMessage('Alerta no válida', 'en')).toBe('Invalid alert.');
    expect(backendMessage('Selecciona un documento no vacío', 'en')).toBe('Choose a non-empty document.');
    expect(backendMessage('Completa el valor izquierdo y el derecho de cada criterio', 'en'))
      .toBe('Fill in the left and right value of each criterion.');
    expect(backendMessage('Añade al menos un criterio', 'en')).toBe('Add at least one criterion.');
  });

  it('en español pasan intactos', () => {
    expect(backendMessage('Introduce un ticker válido', 'es')).toBe('Introduce un ticker válido');
    expect(backendMessage('Añade al menos un criterio', 'es')).toBe('Añade al menos un criterio');
  });
});
