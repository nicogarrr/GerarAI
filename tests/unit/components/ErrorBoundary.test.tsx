import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { ErrorBoundary, withErrorBoundary } from '@/components/ErrorBoundary';

let shouldThrow = true;
function Bomb() {
    if (shouldThrow) throw new Error('boom');
    return <p>contenido recuperado</p>;
}

describe('ErrorBoundary', () => {
    it('un error de render muestra el aviso en español en vez de romper la página', () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        shouldThrow = true;
        render(
            <ErrorBoundary>
                <Bomb />
            </ErrorBoundary>,
        );
        expect(screen.getByText('Algo salió mal')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Intentar de nuevo' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Recargar página' })).toBeInTheDocument();
        // Fuera de desarrollo no se filtran trazas al usuario.
        expect(screen.queryByText(/Detalles técnicos/)).not.toBeInTheDocument();
    });

    it('"Intentar de nuevo" vuelve a montar los hijos cuando el error ya no se da', () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        shouldThrow = true;
        render(
            <ErrorBoundary>
                <Bomb />
            </ErrorBoundary>,
        );
        shouldThrow = false;
        fireEvent.click(screen.getByRole('button', { name: 'Intentar de nuevo' }));
        expect(screen.getByText('contenido recuperado')).toBeInTheDocument();
        expect(screen.queryByText('Algo salió mal')).not.toBeInTheDocument();
    });

    it('respeta un fallback propio y el HOC aísla el fallo al componente envuelto', () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        shouldThrow = true;
        const Safe = withErrorBoundary(Bomb, <p>panel no disponible</p>);
        function Page() {
            const [n] = useState(1);
            return (
                <main>
                    <h1>Cabecera {n}</h1>
                    <Safe />
                </main>
            );
        }
        render(<Page />);
        expect(screen.getByText('panel no disponible')).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Cabecera 1' })).toBeInTheDocument();
        expect(Safe.displayName).toBe('withErrorBoundary(Bomb)');
    });
});
