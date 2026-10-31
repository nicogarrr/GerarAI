import { describe, expect, it, vi } from 'vitest';

import { BACKEND_PAGE_SIZE, fetchAllBackendPages } from '@/lib/paginated-backend';

describe('fetchAllBackendPages', () => {
    it('una página corta: devuelve sus elementos con una sola llamada', async () => {
        const fetchPage = vi.fn(async () => ({ items: [{ id: 1 }, { id: 2 }] }));
        expect(await fetchAllBackendPages(fetchPage)).toEqual([{ id: 1 }, { id: 2 }]);
        expect(fetchPage).toHaveBeenCalledTimes(1);
        expect(fetchPage).toHaveBeenCalledWith(1);
    });

    it('páginas llenas: sigue pidiendo hasta la primera página corta, en orden', async () => {
        const full = Array.from({ length: BACKEND_PAGE_SIZE }, (_, i) => ({ id: `a${i}` }));
        const fetchPage = vi.fn()
            .mockResolvedValueOnce({ items: full })
            .mockResolvedValueOnce({ items: [{ id: 'last' }] });
        const result = await fetchAllBackendPages(fetchPage);
        expect(result).toHaveLength(BACKEND_PAGE_SIZE + 1);
        expect(result.at(-1)).toEqual({ id: 'last' });
        expect(fetchPage).toHaveBeenNthCalledWith(2, 2);
    });

    it('respuesta vacía paginada -> lista vacía', async () => {
        expect(await fetchAllBackendPages(async () => ({ items: [] }))).toEqual([]);
    });

    it('array pelado (contrato antiguo) se acepta como defensa en runtime', async () => {
        expect(await fetchAllBackendPages(async () => [{ id: 1 }])).toEqual([{ id: 1 }]);
    });

    it('respuesta sin items ({} u objeto raro) -> error explícito, no lista vacía disfrazada', async () => {
        await expect(fetchAllBackendPages(async () => ({}) as never)).rejects.toThrow(/sin items/);
        await expect(fetchAllBackendPages(async () => ({ page_info: {} }) as never)).rejects.toThrow(/sin items/);
    });

    it('tope de seguridad: 25 páginas llenas sin agotar -> error explícito, nunca lista parcial', async () => {
        const full = Array.from({ length: BACKEND_PAGE_SIZE }, (_, i) => ({ id: i }));
        const fetchPage = vi.fn(async () => ({ items: full }));
        await expect(fetchAllBackendPages(fetchPage)).rejects.toThrow(/no se entrega una lista parcial/);
        expect(fetchPage).toHaveBeenCalledTimes(25);
    });
});
