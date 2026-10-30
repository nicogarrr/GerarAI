import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const searchStocksWithStatus = vi.fn();
vi.mock('@/lib/actions/finnhub.actions', () => ({
    searchStocksWithStatus: (q: string) => searchStocksWithStatus(q),
}));

import { TickerSearchInput } from '@/components/search/TickerSearchInput';

const stock = (symbol: string, name: string) => ({ symbol, name, exchange: 'NASDAQ', type: 'Common Stock', isInWatchlist: false });

/** Resuelve las promesas pendientes (respuesta del proveedor simulado). */
async function flush() {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
    });
}

/** Escribe en el input con foco y deja pasar el debounce de 300 ms. */
async function typeAndSettle(input: HTMLElement, text: string) {
    act(() => {
        input.focus();
    });
    fireEvent.change(input, { target: { value: text } });
    await act(async () => {
        await vi.advanceTimersByTimeAsync(300);
    });
    await flush();
}

describe('TickerSearchInput', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        searchStocksWithStatus.mockReset();
    });
    afterEach(() => {
        vi.useRealTimers();
    });

    it('debounce: una sola búsqueda tras dejar de escribir, con el texto final', async () => {
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [stock('AMZN', 'Amazon.com Inc')] });
        render(<TickerSearchInput />);
        const input = screen.getByRole('combobox');
        act(() => input.focus());
        fireEvent.change(input, { target: { value: 'A' } });
        fireEvent.change(input, { target: { value: 'AM' } });
        fireEvent.change(input, { target: { value: 'AMZ' } });
        await act(async () => {
            await vi.advanceTimersByTimeAsync(299);
        });
        expect(searchStocksWithStatus).not.toHaveBeenCalled();
        await act(async () => {
            await vi.advanceTimersByTimeAsync(1);
        });
        await flush();
        expect(searchStocksWithStatus).toHaveBeenCalledTimes(1);
        expect(searchStocksWithStatus).toHaveBeenCalledWith('AMZ');
        expect(screen.getByRole('option', { name: /AMZN/ })).toBeInTheDocument();
        expect(input).toHaveAttribute('aria-expanded', 'true');
    });

    it('error del proveedor ≠ "sin resultados": cada caso se dice distinto', async () => {
        searchStocksWithStatus.mockResolvedValueOnce({ status: 'error', stocks: [] });
        render(<TickerSearchInput />);
        const input = screen.getByRole('combobox');
        await typeAndSettle(input, 'ZZZ');
        expect(screen.getByRole('alert')).toHaveTextContent('fallo del proveedor de datos');
        expect(screen.queryByText(/Sin resultados/)).not.toBeInTheDocument();

        searchStocksWithStatus.mockResolvedValueOnce({ status: 'ok', stocks: [] });
        await typeAndSettle(input, 'QQQQ');
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('Sin resultados para «QQQQ».');
    });

    it('una respuesta tardía de una búsqueda vieja no pisa la lista actual (gate F215)', async () => {
        let resolveOld: (v: unknown) => void = () => {};
        searchStocksWithStatus
            .mockImplementationOnce(() => new Promise((r) => { resolveOld = r; }))
            .mockResolvedValueOnce({ status: 'ok', stocks: [stock('AAPL', 'Apple Inc')] });
        render(<TickerSearchInput />);
        const input = screen.getByRole('combobox');
        await typeAndSettle(input, 'MSF');
        await typeAndSettle(input, 'AAP');
        expect(screen.getByRole('option', { name: /AAPL/ })).toBeInTheDocument();
        await act(async () => {
            resolveOld({ status: 'ok', stocks: [stock('MSFT', 'Microsoft Corp')] });
        });
        expect(screen.queryByRole('option', { name: /MSFT/ })).not.toBeInTheDocument();
        expect(screen.getByRole('option', { name: /AAPL/ })).toBeInTheDocument();
    });

    it('Enter elige la primera sugerencia, avisa al consumidor y no vuelve a abrir la lista', async () => {
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [stock('AMZN', 'Amazon.com Inc'), stock('AMZA', 'Otro')] });
        const onSelect = vi.fn();
        const onValueChange = vi.fn();
        render(<TickerSearchInput onSelect={onSelect} onValueChange={onValueChange} />);
        const input = screen.getByRole('combobox');
        await typeAndSettle(input, 'AMZ');
        screen.getByRole('option', { name: /AMZN/ });
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'AMZN' }));
        expect(onValueChange).toHaveBeenLastCalledWith('AMZN');
        expect(input).toHaveValue('AMZN');
        expect(screen.queryByRole('option')).not.toBeInTheDocument();
        await act(async () => {
            await vi.advanceTimersByTimeAsync(1000);
        });
        // Elegir no dispara otra búsqueda con el símbolo elegido.
        expect(searchStocksWithStatus).toHaveBeenCalledTimes(1);
    });

    it('flechas mueven la opción activa (aria-activedescendant) y Escape cierra', async () => {
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [stock('AMZN', 'Amazon.com Inc'), stock('AMD', 'Advanced Micro Devices')] });
        render(<TickerSearchInput />);
        const input = screen.getByRole('combobox');
        await typeAndSettle(input, 'AM');
        screen.getAllByRole('option');
        fireEvent.keyDown(input, { key: 'ArrowDown' });
        fireEvent.keyDown(input, { key: 'ArrowDown' });
        const activeId = input.getAttribute('aria-activedescendant');
        expect(activeId).toBeTruthy();
        expect(document.getElementById(activeId!)).toHaveTextContent('AMD');
        fireEvent.keyDown(input, { key: 'Escape' });
        expect(screen.queryByRole('option')).not.toBeInTheDocument();
        expect(input).toHaveAttribute('aria-expanded', 'false');
    });

    it('Enter con la búsqueda resuelta y sin sugerencias avisa al consumidor con el texto; en vuelo, no', async () => {
        const onEnter = vi.fn();
        searchStocksWithStatus.mockResolvedValueOnce({ status: 'ok', stocks: [] });
        render(<TickerSearchInput onEnterWithoutResults={onEnter} />);
        const input = screen.getByRole('combobox');
        // Antes de que termine la búsqueda (debounce pendiente) Enter no actúa.
        act(() => { input.focus(); });
        fireEvent.change(input, { target: { value: ' kkr ' } });
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(onEnter).not.toHaveBeenCalled();
        await act(async () => { await vi.advanceTimersByTimeAsync(300); });
        await flush();
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(onEnter).toHaveBeenCalledWith('kkr');

        // Proveedor caído: también es «sin sugerencias».
        searchStocksWithStatus.mockResolvedValueOnce({ status: 'error', stocks: [] });
        await typeAndSettle(input, 'ZZZ');
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(onEnter).toHaveBeenLastCalledWith('ZZZ');
    });

    it('Enter con sugerencias sigue eligiendo la primera, no el texto', async () => {
        const onEnter = vi.fn();
        const onSelect = vi.fn();
        searchStocksWithStatus.mockResolvedValue({ status: 'ok', stocks: [stock('AMZN', 'Amazon.com Inc')] });
        render(<TickerSearchInput onEnterWithoutResults={onEnter} onSelect={onSelect} />);
        const input = screen.getByRole('combobox');
        await typeAndSettle(input, 'ama');
        fireEvent.keyDown(input, { key: 'Enter' });
        expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ symbol: 'AMZN' }));
        expect(onEnter).not.toHaveBeenCalled();
    });
});
