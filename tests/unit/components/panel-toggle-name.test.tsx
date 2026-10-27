import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { Panel } from '@/components/ui/panel';

it('separates action and title in the accessible name before and after toggling', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    render(<Panel title="Modelo a largo plazo" collapsible>Contenido</Panel>);
    const toggle = screen.getByRole('button', { name: 'Expandir Modelo a largo plazo' });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(screen.getByRole('button', { name: 'Contraer Modelo a largo plazo' })).toHaveAttribute('aria-expanded', 'true');
    vi.unstubAllGlobals();
});
