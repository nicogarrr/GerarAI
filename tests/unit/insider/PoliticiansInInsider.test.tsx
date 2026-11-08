import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const redirect = vi.fn((url: string) => { throw new Error(`REDIRECT:${url}`); });
vi.mock('next/navigation', () => ({ redirect: (url: string) => redirect(url) }));

import PoliticiansRedirect from '@/app/(root)/politicos/page';
import { politiciansHref } from '@/components/insider/PoliticiansListSection';

// Nico, 8-nov-2026 16:22: «No hagas más pestañas, solo mete lo que aporte valor
// en cosas ya existentes». /politicos deja de ser página: es una sección de
// /insider y su ruta solo redirige, con los mismos filtros.
describe('políticos dentro de /insider', () => {
  it('/politicos redirige a la sección de /insider conservando los filtros', async () => {
    await expect(PoliticiansRedirect({ searchParams: Promise.resolve({ partido: 'D', orden: 'late', ticker: 'X' }) })).rejects.toThrow('REDIRECT:/insider?partido=D&orden=late#politicos');
    await expect(PoliticiansRedirect({ searchParams: Promise.resolve({}) })).rejects.toThrow('REDIRECT:/insider#politicos');
  });

  it('los filtros de la lista enlazan a /insider#politicos, no a una página aparte', () => {
    expect(politiciansHref({ camara: 'all', partido: 'all', orden: 'trades' }, { partido: 'R' })).toBe('/insider?partido=R#politicos');
    expect(politiciansHref({ camara: 'house', partido: 'all', orden: 'late', q: 'pelosi' }, { n: '60' })).toBe('/insider?camara=house&orden=late&q=pelosi&n=60#politicos');
  });

  it('el menú del hub ya no tiene la pestaña Políticos', () => {
    const hub = readFileSync(path.join(process.cwd(), 'app/(root)/inversores/_components/HubNav.tsx'), 'utf8');
    expect(hub).not.toContain('/politicos');
  });
});
