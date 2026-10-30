import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/auth.actions', () => ({ signUpWithEmail: vi.fn() }));
vi.mock('@/components/forms/AccessRequestForm', () => ({ default: () => <form aria-label="Pedir acceso a GerarAI" /> }));

import SignUpForm from '@/components/forms/SignUpForm';

const src = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

describe('Errores y títulos que un lector de pantalla puede encontrar', () => {
    it('la casilla de términos se marca inválida y apunta a su mensaje de error', async () => {
        render(<SignUpForm signUpOpen />);
        const terms = screen.getByRole('checkbox', { name: /He leído y acepto/ });
        expect(terms).toHaveAttribute('aria-invalid', 'false');
        expect(terms).not.toHaveAttribute('aria-describedby');

        fireEvent.submit(terms.closest('form')!);

        await waitFor(() => expect(terms).toHaveAttribute('aria-invalid', 'true'));
        expect(terms).toHaveAccessibleDescription(/Debes aceptar los Términos de uso/);
    });

    it('un filtro guardado tiene título de pestaña propio, no el genérico de la app', () => {
        expect(src('app/(root)/screeners/[screenId]/page.tsx')).toMatch(/export const metadata: Metadata = \{\s*title: 'Resultados del filtro guardado'/);
    });

    it('el aviso de noticias caídas no habla de «dashboard»', () => {
        const news = src('components/NewsSection.tsx');
        expect(news).toContain('El resto de la página sigue funcionando.');
        expect(news).not.toContain('El resto del dashboard');
    });
});
