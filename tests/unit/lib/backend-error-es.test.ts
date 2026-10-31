import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { looksEnglish, spanishBackendMessage } from '@/lib/research/backend-error-es';
import { AppError, getFriendlyErrorMessage } from '@/lib/types/errors';

// Los `detail` del motor llegaban a la UI en inglés (página de cartera,
// resultados de server actions, toasts «Holding no encontrado»).
describe('textos de error del motor en español', () => {
  it('traduce los rechazos conocidos de cartera y movimientos', () => {
    expect(spanishBackendMessage('Holding not found')).toBe('Esa posición ya no existe. Recarga la página.');
    expect(spanishBackendMessage('Transaction not found')).toMatch(/^Ese movimiento ya no existe/);
    expect(spanishBackendMessage('Insufficient shares for sale')).toMatch(/^No puedes vender más acciones/);
    expect(spanishBackendMessage('Position cannot mix transaction currencies')).toMatch(/otra divisa/);
    expect(spanishBackendMessage('Company AAPL not found')).toBe('No se encontró la empresa.');
    expect(spanishBackendMessage("Workflow 'x' not found")).toMatch(/^No se encontró/);
  });

  it('estado HTTP sin detail y motor caído', () => {
    expect(spanishBackendMessage('500 Internal Server Error')).toMatch(/motor de análisis no responde/);
    expect(spanishBackendMessage('404 Not Found')).toMatch(/^No se encontró/);
    expect(spanishBackendMessage('Research engine unavailable for /api/portfolio/summary (timeout); reintenta en unos segundos.')).toMatch(/no responde/);
  });

  it('el español del motor pasa intacto y la referencia se conserva', () => {
    expect(spanishBackendMessage('Sin velas disponibles')).toBe('Sin velas disponibles');
    expect(spanishBackendMessage('rango maximo: 366 dias')).toBe('rango maximo: 366 dias');
    expect(spanishBackendMessage('La importación Flex no está habilitada para esta cuenta.')).toMatch(/^La importación Flex/);
    expect(spanishBackendMessage('Thesis generation failed (ref ab12)')).toMatch(/\(ref ab12\)$/);
  });

  it('los toasts ya no mezclan idiomas («Holding no encontrado»)', () => {
    const err = new AppError('Holding not found', 'RESEARCH_API_ERROR', 404);
    expect(getFriendlyErrorMessage(err)).toBe('Esa posición ya no existe. Recarga la página.');
    expect(getFriendlyErrorMessage(new AppError('Tenant context required', 'RESEARCH_API_ERROR', 400))).not.toMatch(/tenant|context|required/i);
  });

  it('traduce los rechazos de infraestructura y de acceso (auth, rate limit, tenant)', () => {
    expect(spanishBackendMessage('Authentication backend unavailable')).toMatch(/autenticaci/i);
    expect(spanishBackendMessage('Authentication backend unavailable')).not.toMatch(/backend|unavailable/i);
    expect(spanishBackendMessage('Rate limit backend unavailable')).toMatch(/control de peticiones/i);
    expect(spanishBackendMessage('Rate limit backend unavailable')).not.toMatch(/backend|unavailable/i);
    expect(spanishBackendMessage('Research authentication is not configured')).not.toMatch(/research|authentication|configured/i);
    expect(spanishBackendMessage('Tenant access is not active')).toMatch(/cuenta/i);
    expect(spanishBackendMessage('Tenant access is not active')).not.toMatch(/tenant|access|active/i);
  });

  it('traduce los «X not found» de memoria, ProPicks y seguimiento', () => {
    expect(spanishBackendMessage('Claim not found')).toBe('No se encontró la afirmación.');
    expect(spanishBackendMessage('Corporate action not found')).toBe('No se encontró la acción corporativa.');
    expect(spanishBackendMessage('Decision lesson not found')).toBe('No se encontró la lección de decisiones.');
    expect(spanishBackendMessage('Investment principle not found')).toBe('No se encontró el principio de inversión.');
    expect(spanishBackendMessage('KPI candidate not found')).toBe('No se encontró el candidato de KPI.');
    expect(spanishBackendMessage('Management promise not found')).toBe('No se encontró el compromiso de la directiva.');
    expect(spanishBackendMessage('propick run not found')).toBe('No se encontró la ejecución de ProPicks.');
    expect(spanishBackendMessage('Research session not found')).toBe('No se encontró la sesión de investigación.');
    expect(spanishBackendMessage('Review not found')).toBe('No se encontró la revisión.');
    expect(spanishBackendMessage('Source not found')).toBe('No se encontró la fuente.');
  });

  it('guard: ningún detail literal en inglés de las rutas del motor llega en inglés', () => {
    const dir = path.join(process.cwd(), 'data-engine/app/api/routes');
    const details = new Set<string>();
    for (const file of readdirSync(dir).filter((f) => f.endsWith('.py'))) {
      const src = readFileSync(path.join(dir, file), 'utf8');
      for (const m of src.matchAll(/detail=(f?)"([^"]+)"/g)) {
        details.add(m[1] ? m[2].replace(/\{[^}]*\}/g, 'X1') : m[2]);
      }
    }
    expect(details.size).toBeGreaterThan(50);
    const leaks = [...details].filter((d) => looksEnglish(d) && looksEnglish(spanishBackendMessage(d)));
    expect(leaks).toEqual([]);
    const english = [...details].filter((d) => looksEnglish(d));
    expect(english.length).toBeGreaterThan(20);
  });
});
