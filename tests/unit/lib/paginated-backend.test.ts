import { describe, expect, it, vi } from 'vitest';

import { BACKEND_PAGE_SIZE, fetchAllBackendPages, type BackendPageInfo } from '@/lib/paginated-backend';
import { AppError } from '@/lib/types/errors';

const key = (item: { id: number | string }) => String(item.id);
const pageInfo = (over: Partial<BackendPageInfo> = {}): BackendPageInfo => ({
    page: 1, page_size: BACKEND_PAGE_SIZE, total_items: 0, total_pages: 1,
    has_next: false, has_prev: false, ...over,
});
const fullPage = (prefix: string) =>
    Array.from({ length: BACKEND_PAGE_SIZE }, (_, i) => ({ id: `${prefix}${i}` }));

describe('fetchAllBackendPages', () => {
    it('una página corta: devuelve sus elementos con una sola llamada', async () => {
        const fetchPage = vi.fn(async () => ({ items: [{ id: 1 }, { id: 2 }], page_info: pageInfo() }));
        expect(await fetchAllBackendPages(fetchPage, key)).toEqual([{ id: 1 }, { id: 2 }]);
        expect(fetchPage).toHaveBeenCalledTimes(1);
        expect(fetchPage).toHaveBeenCalledWith(1);
    });

    it('201 elementos en dos páginas (200 + 1): agrega en orden y para en la corta', async () => {
        const fetchPage = vi.fn()
            .mockResolvedValueOnce({ items: fullPage('a'), page_info: pageInfo({ has_next: true, total_pages: 2, total_items: 201 }) })
            .mockResolvedValueOnce({ items: [{ id: 'last' }], page_info: pageInfo({ page: 2, total_items: 201 }) });
        const result = await fetchAllBackendPages(fetchPage, key);
        expect(result).toHaveLength(201);
        expect(result.at(-1)).toEqual({ id: 'last' });
        expect(fetchPage).toHaveBeenNthCalledWith(2, 2);
    });

    it('criterio de parada es page_info.has_next: página LLENA con has_next=false termina', async () => {
        const fetchPage = vi.fn(async () => ({ items: fullPage('a'), page_info: pageInfo({ has_next: false }) }));
        const result = await fetchAllBackendPages(fetchPage, key);
        expect(result).toHaveLength(BACKEND_PAGE_SIZE);
        expect(fetchPage).toHaveBeenCalledTimes(1);
    });

    it('sin page_info: respaldo = primera página corta (una llena no basta)', async () => {
        const fetchPage = vi.fn()
            .mockResolvedValueOnce({ items: fullPage('a') })
            .mockResolvedValueOnce({ items: [{ id: 'last' }] });
        const result = await fetchAllBackendPages(fetchPage, key);
        expect(result).toHaveLength(BACKEND_PAGE_SIZE + 1);
        expect(fetchPage).toHaveBeenCalledTimes(2);
    });

    it('respuesta vacía paginada -> lista vacía', async () => {
        expect(await fetchAllBackendPages(async () => ({ items: [], page_info: pageInfo() }), key)).toEqual([]);
    });

    it('array pelado (contrato antiguo) solo vale como primera página', async () => {
        expect(await fetchAllBackendPages(async () => [{ id: 1 }], key)).toEqual([{ id: 1 }]);
        const fetchPage = vi.fn()
            .mockResolvedValueOnce({ items: fullPage('a'), page_info: pageInfo({ has_next: true }) })
            .mockResolvedValueOnce([{ id: 'last' }]);
        await expect(fetchAllBackendPages(fetchPage, key)).rejects.toThrow(/sin envoltura paginada/);
    });

    it('página repetida (mismo primer elemento) -> error inmediato, sin consumir el tope', async () => {
        const fetchPage = vi.fn(async () => ({ items: fullPage('a'), page_info: pageInfo({ has_next: true, total_pages: 99 }) }));
        await expect(fetchAllBackendPages(fetchPage, key)).rejects.toThrow(/repite el primer elemento/);
        expect(fetchPage).toHaveBeenCalledTimes(2);
    });

    it('null/undefined intermedio -> error, nunca lista parcial entregada como completa', async () => {
        const fetchPage = vi.fn()
            .mockResolvedValueOnce({ items: fullPage('a'), page_info: pageInfo({ has_next: true }) })
            .mockResolvedValueOnce(null);
        await expect(fetchAllBackendPages(fetchPage, key)).rejects.toThrow(/sin items/);
        const nullFirst = vi.fn(async () => null);
        await expect(fetchAllBackendPages(nullFirst, key)).rejects.toThrow(/sin items/);
    });

    it('respuesta sin items ({} u objeto raro) -> error explícito, no lista vacía disfrazada', async () => {
        await expect(fetchAllBackendPages(async () => ({}) as never, key)).rejects.toThrow(/sin items/);
        await expect(fetchAllBackendPages(async () => ({ page_info: pageInfo() }) as never, key)).rejects.toThrow(/sin items/);
    });

    it('tope de seguridad: 25 páginas con has_next=true -> error explícito', async () => {
        let n = 0;
        const fetchPage = vi.fn(async () => ({ items: fullPage(`p${n++}-`), page_info: pageInfo({ has_next: true, total_pages: 999 }) }));
        await expect(fetchAllBackendPages(fetchPage, key)).rejects.toThrow(/no se entrega una lista parcial/);
        expect(fetchPage).toHaveBeenCalledTimes(25);
    });

    it('un 401 del backend se propaga tal cual (no se traga ni se convierte en vacío)', async () => {
        const authError = new AppError('No autorizado', 'RESEARCH_API_ERROR', 401);
        const fetchPage = vi.fn(async () => { throw authError; });
        await expect(fetchAllBackendPages(fetchPage, key)).rejects.toBe(authError);
    });
});
