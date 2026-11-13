import { describe, expect, it } from 'vitest';
import { sectionErrorKey } from '@/lib/section-error';

describe('sectionErrorKey', () => {
  it('distingue un timeout del backend de un corte de conexión', () => {
    expect(sectionErrorKey(new Error('Research engine unavailable for /api/x (timeout de 3000 ms); reintenta en unos segundos.')))
      .toBe('ui.sectionError.timeout');
    expect(sectionErrorKey(new Error('timed out'))).toBe('ui.sectionError.timeout');
    expect(sectionErrorKey(new DOMException('signal timed out', 'TimeoutError'))).toBe('ui.sectionError.timeout');
    expect(sectionErrorKey(new DOMException('The operation was aborted', 'AbortError'))).toBe('ui.sectionError.timeout');
  });

  it('un corte de conexión real sigue siendo network', () => {
    expect(sectionErrorKey(new Error('fetch fallido'))).toBe('ui.sectionError.network');
    expect(sectionErrorKey(new Error('network error'))).toBe('ui.sectionError.network');
    expect(sectionErrorKey(new Error('ECONNREFUSED'))).toBe('ui.sectionError.network');
  });

  it('sesión, servidor y genérico no cambian', () => {
    expect(sectionErrorKey(new Error('401 Unauthorized'))).toBe('ui.sectionError.session');
    expect(sectionErrorKey(new Error('500 Internal Server Error'))).toBe('ui.sectionError.server');
    expect(sectionErrorKey(new Error('otra cosa'))).toBe('ui.sectionError.generic');
    expect(sectionErrorKey(null)).toBe('ui.sectionError.generic');
  });
});
