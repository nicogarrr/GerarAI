import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GemItem } from '@/lib/actions/propicks-gems.actions';

const { getGems, reviewGems } = vi.hoisted(() => ({ getGems: vi.fn(), reviewGems: vi.fn() }));
vi.mock('@/lib/actions/propicks-gems.actions', () => ({ getGems, reviewGems }));

import GemsView from '@/components/proPicks/GemsView';

const gem = (over: Partial<GemItem> = {}): GemItem => ({
    ticker: 'ABC',
    name: 'Abc Corp',
    score: 73.25,
    market_cap: 1_500_000_000,
    reasons: [{ key: 'fcf_yield', value: 0.064, source: 'FMP' }] as GemItem['reasons'],
    ...over,
});

const reviewButton = () => screen.getByRole('button', { name: /Revisar con IA|Revisar|Review/i });
const refreshButtons = () => screen.getAllByRole('button', { name: /Actualizar|Refresh/i });

beforeEach(() => {
    getGems.mockReset();
    reviewGems.mockReset();
});

describe('GemsView: estados de carga, error y revision', () => {
    it('si getGems devuelve error muestra el aviso, no el vacio, y el boton de revisar sigue deshabilitado', async () => {
        getGems.mockResolvedValue({ error: 'x' });
        render(<GemsView />);
        await waitFor(() => expect(screen.getByText(/No se pudieron cargar|could not be loaded|couldn't/i)).toBeInTheDocument());
        expect(reviewButton()).toBeDisabled();
        // con error no se pinta el estado vacio (no se confunde un fallo con "sin joyas")
        expect(screen.queryByText(/Sin joyas|No gems/i)).not.toBeInTheDocument();
    });

    it('sin joyas: estado vacio con su boton, que vuelve a pedir los datos', async () => {
        getGems.mockResolvedValueOnce([]).mockResolvedValueOnce([gem()]);
        render(<GemsView />);
        await waitFor(() => expect(screen.getAllByRole('button', { name: /Actualizar|Refresh/i }).length).toBe(2));
        fireEvent.click(refreshButtons()[1]);
        await waitFor(() => expect(screen.getByText('ABC')).toBeInTheDocument());
        expect(getGems).toHaveBeenCalledTimes(2);
    });

    it('mientras carga, los botones quedan deshabilitados', async () => {
        let resolve!: (v: GemItem[]) => void;
        getGems.mockReturnValue(new Promise<GemItem[]>((r) => { resolve = r; }));
        render(<GemsView />);
        await waitFor(() => expect(getGems).toHaveBeenCalled());
        expect(refreshButtons()[0]).toBeDisabled();
        await act(async () => resolve([gem()]));
        expect(refreshButtons()[0]).not.toBeDisabled();
    });

    it('revision con exito: cuenta las revisadas, pinta veto, conserva, riesgos, tesis y confianza', async () => {
        getGems.mockResolvedValue([gem()]);
        reviewGems.mockResolvedValue([
            gem({ ticker: 'KEEP', review_status: 'reviewed', decision: 'keep', confidence: 0.8, thesis: 'Tesis KEEP', risks: ['riesgo uno', 'riesgo dos'], invalidation: 'cae el margen' }),
            gem({ ticker: 'VETO', review_status: 'reviewed', decision: 'veto', confidence: null, veto_reason: 'motivo del veto', risks: [], thesis: null }),
            gem({ ticker: 'NOIA', review_status: 'sin_revision_ia' }),
            gem({ ticker: 'NOIA2', review_status: 'sin_revision_ia' }),
            gem({ ticker: 'PLAIN', market_cap: undefined }),
        ]);
        render(<GemsView />);
        await waitFor(() => expect(screen.getByText('ABC')).toBeInTheDocument());
        fireEvent.click(reviewButton());
        await waitFor(() => expect(screen.getByText('KEEP')).toBeInTheDocument());
        expect(screen.getByRole('status')).toHaveTextContent('Revisión IA completada: 2 de 5 joyas revisadas.');
        expect(screen.getByText('Tesis KEEP')).toBeInTheDocument();
        expect(screen.getByText('riesgo uno')).toBeInTheDocument();
        expect(screen.getByText('riesgo dos')).toBeInTheDocument();
        expect(screen.getByText(/cae el margen/)).toBeInTheDocument();
        expect(screen.getByText('motivo del veto')).toBeInTheDocument();
        // confianza solo donde existe: una sola linea de confianza (KEEP; VETO la trae null)
        expect(screen.getAllByText(/80\s?%/)).toHaveLength(1);
        // sin revision IA: aviso por joya
        expect(screen.getAllByText(/Sin revisi[oó]n IA|not reviewed|Not reviewed/i).length).toBeGreaterThan(0);
    });

    it('un veto sin motivo no inventa texto y una conserva no muestra motivo de veto', async () => {
        getGems.mockResolvedValue([gem()]);
        reviewGems.mockResolvedValue([
            gem({ ticker: 'V1', review_status: 'reviewed', decision: 'veto', veto_reason: null }),
            gem({ ticker: 'K1', review_status: 'reviewed', decision: 'keep', veto_reason: 'no debe verse' }),
        ]);
        render(<GemsView />);
        await waitFor(() => expect(screen.getByText('ABC')).toBeInTheDocument());
        fireEvent.click(reviewButton());
        await waitFor(() => expect(screen.getByText('V1')).toBeInTheDocument());
        expect(screen.queryByText('no debe verse')).not.toBeInTheDocument();
    });

    it('si la cadena LLM no esta disponible (ninguna revisada) lo dice, en vez de parecer que el boton no hace nada', async () => {
        getGems.mockResolvedValue([gem()]);
        reviewGems.mockResolvedValue([gem({ review_status: 'sin_revision_ia' })]);
        render(<GemsView />);
        await waitFor(() => expect(screen.getByText('ABC')).toBeInTheDocument());
        fireEvent.click(reviewButton());
        await waitFor(() => expect(screen.getByRole('status').textContent?.trim().length).toBeGreaterThan(0));
        expect(screen.getByRole('status')).toHaveClass('text-amber-300');
        expect(screen.getByRole('status')).toHaveTextContent(/La revisión IA no está disponible ahora mismo/);
        expect(screen.getByRole('status')).not.toHaveTextContent(/completada/);
    });

    it('si la revision falla muestra el error del servidor y conserva las joyas', async () => {
        getGems.mockResolvedValue([gem()]);
        reviewGems.mockResolvedValue({ error: 'No se pudo completar la revisión.' });
        render(<GemsView />);
        await waitFor(() => expect(screen.getByText('ABC')).toBeInTheDocument());
        fireEvent.click(reviewButton());
        await waitFor(() => expect(screen.getByText('No se pudo completar la revisión.')).toBeInTheDocument());
        expect(screen.getByText('ABC')).toBeInTheDocument();
    });

    it('mientras revisa: boton ocupado (aria-busy) y deshabilitado', async () => {
        getGems.mockResolvedValue([gem()]);
        let resolve!: (v: GemItem[]) => void;
        reviewGems.mockReturnValue(new Promise<GemItem[]>((r) => { resolve = r; }));
        render(<GemsView />);
        await waitFor(() => expect(screen.getByText('ABC')).toBeInTheDocument());
        fireEvent.click(reviewButton());
        await waitFor(() => expect(document.querySelector('button[aria-busy="true"]')).not.toBeNull());
        expect(document.querySelector('button[aria-busy="true"]')).toBeDisabled();
        await act(async () => resolve([gem({ review_status: 'reviewed', decision: 'keep' })]));
        expect(document.querySelector('button[aria-busy="true"]')).toBeNull();
    });

    it('una joya sin capitalizacion no pinta el separador de capitalizacion', async () => {
        getGems.mockResolvedValue([gem({ market_cap: undefined, name: 'Solo Nombre' })]);
        render(<GemsView />);
        await waitFor(() => expect(screen.getByText('ABC')).toBeInTheDocument());
        expect(screen.getByText('Solo Nombre').textContent).not.toContain('·');
    });
});
