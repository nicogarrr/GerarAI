import { readFileSync } from 'node:fs';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), prefetch: vi.fn() }) }));
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: vi.fn().mockResolvedValue({ status: 'ok', stocks: [] }),
    getPopularStocks: vi.fn().mockResolvedValue([]),
}));

import SearchCommand from '@/components/SearchCommand';
import { getSearchCommandSnapshot, closeSearchCommand } from '@/lib/search/search-command-store';

describe('SearchCommand: gatillo eager + paleta diferida', () => {
    it('keeps the heavy dialog out of static imports and behind the owning open state', () => {
        const source = readFileSync(`${process.cwd()}/components/SearchCommand.tsx`, 'utf8');
        expect(source).toMatch(/dynamic\(\(\) => import\(['"]@\/components\/SearchCommandDialog['"]\)/);
        expect(source).not.toMatch(/from\s+['"]cmdk['"]/);
        expect(source).not.toMatch(/from\s+['"][^'"]*(?:SearchCommandDialog|ui\/command|finnhub\.actions)['"]/);
        expect(source).toMatch(/ownerId === instanceId\s*&&\s*\(\s*<SearchCommandDialog/);
    });
    it('monta el gatillo sin abrir nada y sin estado de store', () => {
        render(<SearchCommand renderAs="icon" />);
        expect(screen.getByRole('button', { name: 'Abrir buscador' })).toBeInTheDocument();
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(getSearchCommandSnapshot()).toEqual({ open: false, ownerId: null });
    });

    it('al pulsar, el store abre con esta instancia como dueña y la paleta (chunk diferido) llega', async () => {
        render(<SearchCommand renderAs="icon" />);
        fireEvent.pointerDown(screen.getByRole('button', { name: 'Abrir buscador' }));
        fireEvent.click(screen.getByRole('button', { name: 'Abrir buscador' }));
        expect(getSearchCommandSnapshot().open).toBe(true);
        expect(getSearchCommandSnapshot().ownerId).not.toBeNull();
        // El diálogo carga asíncrono (next/dynamic): aparece cuando llega el chunk.
        await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
        expect(screen.getByLabelText('Buscar acciones o secciones')).toBeInTheDocument();
        closeSearchCommand();
    });

    it('Ctrl+K abre la instancia cuyo gatillo está visible (atajo eager, sin paleta cargada)', async () => {
        render(<SearchCommand renderAs="icon" />);
        fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
        expect(getSearchCommandSnapshot().open).toBe(true);
        await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
        closeSearchCommand();
    });
});
