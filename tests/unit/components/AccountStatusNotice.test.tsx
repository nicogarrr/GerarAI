import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import AccountStatusNotice from '@/components/auth/AccountStatusNotice';

// brand-btn fija h-12 sin centrado propio: en un <button> el navegador centra
// el texto solo, pero en un <a> inline-block quedaba pegado arriba (visto en
// /cuenta-pendiente a 390 px). El enlace debe centrar su contenido como hace
// el componente Button (inline-flex items-center justify-center).
describe('AccountStatusNotice', () => {
    it.each(['pendiente', 'rechazada'] as const)('el enlace a /sign-in centra el texto en vertical (%s)', (state) => {
        const { container } = render(<AccountStatusNotice state={state} />);
        const link = container.querySelector('a[href="/sign-in"]');
        expect(link).not.toBeNull();
        expect(link!.className).toContain('items-center');
        expect(link!.className).toContain('justify-center');
        expect(link!.className).not.toContain('inline-block');
    });
});
