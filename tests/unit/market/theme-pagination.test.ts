import { describe, expect, it } from 'vitest';

import { paginateThemes, parseThemePage, themePageHref, THEMES_PAGE_SIZE } from '@/lib/market/theme-pagination';

const items = Array.from({ length: 14 }, (_, i) => i + 1);

describe('parseThemePage', () => {
  it('acepta enteros >= 1 y cae a 1 con cualquier otra cosa', () => {
    expect(parseThemePage('3')).toBe(3);
    expect(parseThemePage(['2', '5'])).toBe(2);
    for (const bad of [undefined, '', '0', '-1', '1.5', 'abc', '2e3', '99999999']) expect(parseThemePage(bad)).toBe(1);
  });
});

describe('paginateThemes', () => {
  it('corta por tamaño de página y cuenta páginas', () => {
    const p = paginateThemes(items, 1);
    expect(p).toMatchObject({ page: 1, pages: Math.ceil(14 / THEMES_PAGE_SIZE), total: 14 });
    expect(p.items).toEqual(items.slice(0, THEMES_PAGE_SIZE));
    expect(paginateThemes(items, 3).items).toEqual(items.slice(12));
  });
  it('una página fuera de rango va a la última, nunca vacía', () => {
    const p = paginateThemes(items, 99);
    expect(p.page).toBe(p.pages);
    expect(p.items.length).toBeGreaterThan(0);
  });
  it('lista vacía: una página, sin elementos', () => {
    expect(paginateThemes([], 1)).toEqual({ items: [], page: 1, pages: 1, total: 0 });
  });
});

describe('themePageHref', () => {
  it('conserva el orden y omite pagina=1', () => {
    expect(themePageHref('ytd', 1)).toBe('/temas');
    expect(themePageHref('ytd', 2)).toBe('/temas?pagina=2');
    expect(themePageHref('1m', 1)).toBe('/temas?orden=1m');
    expect(themePageHref('1m', 3)).toBe('/temas?orden=1m&pagina=3');
  });
});
