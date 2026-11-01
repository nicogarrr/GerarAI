import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import HelpTabs from '@/components/help/HelpTabs';
import { LocaleProvider } from '@/lib/i18n/client';

describe('Centro de ayuda en inglés', () => {
    it('en inglés', () => {
        render(<LocaleProvider locale="en"><HelpTabs /></LocaleProvider>);
        expect(screen.getByRole('heading', { level: 1, name: 'Help center' })).toBeTruthy();
        expect(screen.getByRole('tab', { name: 'Documentation' })).toBeTruthy();
        expect(screen.getByText('Is this financial advice?')).toBeTruthy();
        expect(screen.getByText('require signing in')).toBeTruthy();
    });

    it('en español no cambia', () => {
        render(<LocaleProvider locale="es"><HelpTabs /></LocaleProvider>);
        expect(screen.getByRole('heading', { level: 1, name: 'Centro de ayuda' })).toBeTruthy();
        expect(screen.getByRole('tab', { name: 'Documentación' })).toBeTruthy();
        expect(screen.getByText('¿Esto es asesoramiento financiero?')).toBeTruthy();
    });
});
