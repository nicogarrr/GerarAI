import { fireEvent, render, screen } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('sonner', () => ({ toast: { warning: vi.fn() } }));

import { FileUploadInput } from '@/components/forms/FileUploadInput';

/** jsdom no deja asignar input.files: se inyecta como Playwright lo deja. */
function setFiles(input: HTMLInputElement, files: File[]) {
    Object.defineProperty(input, 'files', { value: files, configurable: true });
}

afterEach(() => {
    document.querySelectorAll('[data-ssr-test]').forEach((el) => el.remove());
});

describe('FileUploadInput', () => {
    it('shows a file chosen BEFORE hydration once React hydrates', async () => {
        // El escenario real del rojo F142: la página sirve el HTML, el usuario
        // (o Playwright con 2 CPU) elige el archivo ANTES de que React conecte
        // el onChange. El input nativo conserva el FileList; el estado visible
        // («Ningún archivo seleccionado») debe sincronizarse al hidratar.
        const container = document.createElement('div');
        container.setAttribute('data-ssr-test', '');
        container.innerHTML = renderToString(<FileUploadInput name="document" />);
        document.body.append(container);
        const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
        setFiles(input, [new File(['contenido'], 'memo-2019.txt', { type: 'text/plain' })]);
        render(<FileUploadInput name="document" />, { container, hydrate: true });
        expect(await screen.findByText('memo-2019.txt')).toBeVisible();
    });
    it('keeps the hydrated change and reset behavior', () => {
        render(
            <form>
                <FileUploadInput name="document" />
                <button type="reset">Limpiar</button>
            </form>,
        );
        const input = screen.getByLabelText('Elegir archivo') as HTMLInputElement;
        setFiles(input, [new File(['contenido'], 'carta-q3.txt', { type: 'text/plain' })]);
        fireEvent.change(input);
        expect(screen.getByText('carta-q3.txt')).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Limpiar' }));
        expect(screen.getByText('Ningún archivo seleccionado')).toBeVisible();
        expect(screen.queryByText('carta-q3.txt')).toBeNull();
    });
    it('oversized files warn, block submit and re-enable after a valid pick', () => {
        const submit = vi.fn();
        render(
            <form onSubmit={(event) => { event.preventDefault(); submit(); }}>
                <FileUploadInput name="document" maxMB={1} />
                <button type="submit">Subir</button>
            </form>,
        );
        const input = screen.getByLabelText('Elegir archivo') as HTMLInputElement;
        const big = new File([new Uint8Array(2 * 1024 * 1024)], 'grande.txt', { type: 'text/plain' });
        setFiles(input, [big]);
        fireEvent.change(input);
        expect(screen.getByRole('alert')).toHaveTextContent(/supera el límite|too big|límite/i);
        const button = screen.getByRole('button', { name: 'Subir' });
        expect(button).toBeDisabled();
        fireEvent.submit(input.closest('form')!);
        expect(submit).not.toHaveBeenCalled();
        setFiles(input, [new File(['ok'], 'peque.txt', { type: 'text/plain' })]);
        fireEvent.change(input);
        expect(button).toBeEnabled();
        expect(screen.queryByRole('alert')).toBeNull();
        fireEvent.click(button);
        expect(submit).toHaveBeenCalledOnce();
    });
    it('clearing the selection restores the empty state and validity', () => {
        render(<FileUploadInput name="document" />);
        const input = screen.getByLabelText('Elegir archivo') as HTMLInputElement;
        setFiles(input, [new File(['contenido'], 'carta-q3.txt')]);
        fireEvent.change(input);
        expect(screen.getByText('carta-q3.txt')).toBeVisible();
        setFiles(input, []);
        fireEvent.change(input);
        expect(screen.getByText('Ningún archivo seleccionado')).toBeVisible();
        expect(input.validationMessage).toBe('');
    });
    it('a form reset also restores the submit buttons', () => {
        render(
            <form>
                <FileUploadInput name="document" maxMB={1} />
                <button type="submit">Subir</button>
                <button type="reset">Limpiar</button>
            </form>,
        );
        const input = screen.getByLabelText('Elegir archivo') as HTMLInputElement;
        setFiles(input, [new File([new Uint8Array(2 * 1024 * 1024)], 'grande.txt')]);
        fireEvent.change(input);
        const button = screen.getByRole('button', { name: 'Subir' });
        expect(button).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Limpiar' }));
        expect(screen.getByText('Ningún archivo seleccionado')).toBeVisible();
        expect(button).toBeEnabled();
    });
    it('unmounting restores the buttons it disabled', () => {
        const { unmount } = render(
            <form>
                <FileUploadInput name="document" maxMB={1} />
                <button type="submit">Subir</button>
            </form>,
        );
        const input = screen.getByLabelText('Elegir archivo') as HTMLInputElement;
        setFiles(input, [new File([new Uint8Array(2 * 1024 * 1024)], 'grande.txt')]);
        fireEvent.change(input);
        expect(screen.getByRole('button', { name: 'Subir' })).toBeDisabled();
        const button = screen.getByRole('button', { name: 'Subir' });
        unmount();
        expect(button).not.toBeDisabled();
    });
    it('hydration with no file chosen keeps the empty state', () => {
        const container = document.createElement('div');
        container.setAttribute('data-ssr-test', '');
        container.innerHTML = renderToString(<FileUploadInput name="document" />);
        document.body.append(container);
        render(<FileUploadInput name="document" />, { container, hydrate: true });
        expect(screen.getByText('Ningún archivo seleccionado')).toBeVisible();
    });
});
