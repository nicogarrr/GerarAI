import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { OnlineBanner } from '@/components/OnlineBanner';

function setOnline(value: boolean) {
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(value);
}

describe('OnlineBanner', () => {
    afterEach(() => {
        delete document.body.dataset.test;
    });

    it('con conexión la live region existe pero no muestra aviso ni reserva alto', () => {
        setOnline(true);
        render(<OnlineBanner />);
        const region = screen.getByRole('status');
        expect(region).toHaveAttribute('aria-live', 'polite');
        expect(region).toHaveClass('sr-only');
        expect(region).toBeEmptyDOMElement();
        expect(region).not.toHaveAttribute('data-online-banner');
    });

    it('sin conexión anuncia el aviso en la MISMA region (no se monta otra)', () => {
        setOnline(true);
        render(<OnlineBanner />);
        const before = screen.getByRole('status');

        setOnline(false);
        act(() => {
            window.dispatchEvent(new Event('offline'));
        });

        const after = screen.getByRole('status');
        expect(after).toBe(before);
        expect(after).toHaveTextContent(/^Sin conexión\./);
        expect(after).toHaveAttribute('data-online-banner');
        expect(after).not.toHaveClass('sr-only');
    });

    it('al volver la conexión el aviso desaparece', () => {
        setOnline(false);
        render(<OnlineBanner />);
        expect(screen.getByRole('status')).toHaveTextContent('Sin conexión');

        setOnline(true);
        act(() => {
            window.dispatchEvent(new Event('online'));
        });
        expect(screen.getByRole('status')).toBeEmptyDOMElement();
        expect(screen.getByRole('status')).toHaveClass('sr-only');
    });
});
