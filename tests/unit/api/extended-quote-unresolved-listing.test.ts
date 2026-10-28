import { beforeEach, describe, expect, it, vi } from 'vitest';

const { request, user } = vi.hoisted(() => ({ request: vi.fn(), user: vi.fn() }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: user }));
vi.mock('@/lib/research/client', () => ({ researchRequest: request }));
vi.mock('@/lib/e2e-market-fixture', () => ({ isE2EMarketFixtureEnabled: () => false }));

import { GET } from '@/app/api/companies/[ticker]/extended-quote/route';

const call = (ticker: string, query = '?resolveListing=1') =>
  GET(new Request(`http://localhost/api/companies/${ticker}/extended-quote${query}`), { params: Promise.resolve({ ticker }) });

// Suite E2E de flujos (28-oct-2026): cada visita a la ficha de un listado sin
// correspondencia de bolsa validada (p. ej. MC.PA en Euronext París) dejaba
// un 404 en la consola del navegador. «Cotización no disponible» es una
// respuesta válida del recurso (el cliente ya la pinta como N/D), no un error.
describe('extended-quote con resolveListing y listado sin correspondencia', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    user.mockResolvedValue({ id: 'u1' });
  });

  it('responde 200 {status: unavailable}, sin pedir la cotización de un ticker adivinado', async () => {
    request.mockResolvedValueOnce({ ticker: 'MC.PA', exchange: 'NYSE EURONEXT - EURONEXT PARIS', currency: 'EUR' });
    const response = await call('MC.PA');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'unavailable' });
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('un listado resuelto sigue pidiendo la cotización del símbolo real', async () => {
    request
      .mockResolvedValueOnce({ ticker: 'SAN', exchange: 'BME', currency: 'EUR' })
      .mockResolvedValueOnce({ status: 'ok', price: 4.1 });
    const response = await call('SAN');
    expect(response.status).toBe(200);
    expect(request.mock.calls[1][0]).toBe('/api/companies/SAN.MC/extended-quote');
  });
});
