import { describe, expect, it } from 'vitest';
import { AppError, getFriendlyErrorMessage } from '@/lib/types/errors';

describe('mensajes de error de la UI en el idioma elegido', () => {
  it('English when locale is en', () => {
    expect(getFriendlyErrorMessage(new Error('fetch failed'), { locale: 'en' })).toBe("The analysis engine isn't responding right now. Try again in a few seconds.");
    expect(getFriendlyErrorMessage(new Error('Failed to find Server Action'), { locale: 'en' })).toBe('A new version of the app is available: reload the page.');
    expect(getFriendlyErrorMessage(new Error('already exists'), { locale: 'en' })).toBe('You already follow this ticker.');
    expect(getFriendlyErrorMessage(new AppError('x', 'AUTHORIZATION_ERROR', 403), { locale: 'en' })).toBe("You don't have permission for this action.");
    expect(getFriendlyErrorMessage(new AppError('x', 'AUTH_ERROR', 401), { locale: 'en' })).toBe('You need to sign in to continue.');
    expect(getFriendlyErrorMessage(new Error('A valid ticker is required'), { locale: 'en' })).toBe('Enter a valid ticker.');
    expect(getFriendlyErrorMessage(new Error('Rate limit exceeded'), { locale: 'en' })).toBe('Too many requests. Wait a moment and try again.');
    expect(getFriendlyErrorMessage(new Error('Holding not found'), { locale: 'en' })).toBe('Holding not found.');
    expect(getFriendlyErrorMessage(new Error('some_internal_code'), { locale: 'en' })).toBe("The operation couldn't be completed. Please try again.");
  });
  it('Spanish by default, unchanged', () => {
    expect(getFriendlyErrorMessage(new Error('fetch failed'))).toBe('El motor de análisis no responde ahora mismo. Reintenta en unos segundos.');
    expect(getFriendlyErrorMessage(new Error('already exists'))).toBe('Ya sigues este ticker.');
    expect(getFriendlyErrorMessage(new Error('A valid ticker is required'))).toBe('Introduce un ticker válido.');
    expect(getFriendlyErrorMessage(new AppError('x', 'AUTH_ERROR', 401))).toBe('Necesitas iniciar sesión para continuar.');
    expect(getFriendlyErrorMessage(new Error('custom duplicate'), { duplicateMessage: 'Ya está en la lista.' })).toBe('Ya está en la lista.');
  });
});
