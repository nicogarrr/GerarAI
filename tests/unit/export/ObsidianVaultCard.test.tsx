import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ObsidianVaultCard from '@/components/export/ObsidianVaultCard';

const mockFetch = vi.fn();

describe('ObsidianVaultCard (vault por proxy same-origin)', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal('fetch', mockFetch);
        URL.createObjectURL = vi.fn(() => 'blob:mock-vault');
        URL.revokeObjectURL = vi.fn();
        mockFetch.mockResolvedValue(new Response('zip-bytes', { status: 200 }));
    });
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('pide confirmación, descarga por fetch + blob y no navega al proxy', async () => {
        render(<ObsidianVaultCard />);
        fireEvent.click(screen.getByRole('link', { name: /Descargar para Obsidian/ }));
        // La descarga NO arranca sin confirmar: sigue en el diálogo.
        expect(screen.getByText('¿Descargar tus tesis y datos de cartera en un archivo ZIP en este dispositivo?')).toBeInTheDocument();
        expect(mockFetch).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: 'Descargar' }));
        await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
        expect(mockFetch).toHaveBeenCalledWith('/api/obsidian/vault.zip');
        // El enlace conserva el href directo como mejora progresiva sin JS.
        expect(screen.getByRole('link', { name: /Descargar para Obsidian/ })).toHaveAttribute('href', '/api/obsidian/vault.zip');
    });

    it('cancelar cierra el diálogo sin tocar el proxy', async () => {
        render(<ObsidianVaultCard />);
        fireEvent.click(screen.getByRole('link', { name: /Descargar para Obsidian/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
        await waitFor(() => expect(screen.queryByText('¿Descargar tus tesis y datos de cartera en un archivo ZIP en este dispositivo?')).not.toBeInTheDocument());
        expect(mockFetch).not.toHaveBeenCalled();
    });

    it('502 del proxy: error inline en la tarjeta, no un JSON fuera de la app', async () => {
        mockFetch.mockResolvedValue(new Response('bad gateway', { status: 502 }));
        render(<ObsidianVaultCard />);
        fireEvent.click(screen.getByRole('link', { name: /Descargar para Obsidian/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Descargar' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo descargar el vault. Inténtalo de nuevo en unos segundos.');
        expect(URL.createObjectURL).not.toHaveBeenCalled();
    });

    it('con una descarga en curso, otro clic no reabre la confirmación ni duplica el fetch', async () => {
        mockFetch.mockReturnValue(new Promise(() => {}));
        render(<ObsidianVaultCard />);
        fireEvent.click(screen.getByRole('link', { name: /Descargar para Obsidian/ }));
        fireEvent.click(screen.getByRole('button', { name: 'Descargar' }));
        const link = await screen.findByRole('link', { name: /Descargando/ });
        expect(link).toHaveAttribute('aria-busy', 'true');
        fireEvent.click(link);
        expect(screen.queryByText('¿Descargar tus tesis y datos de cartera en un archivo ZIP en este dispositivo?')).not.toBeInTheDocument();
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
});
