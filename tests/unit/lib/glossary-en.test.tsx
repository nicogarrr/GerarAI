import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { GlossaryTerm, MoatTerm } from '@/components/GlossaryTerm';
import { TooltipProvider } from '@/components/ui/tooltip';
import { glossary, glossaryEn, glossaryFor, moatLabel } from '@/lib/glossary';
import { LocaleProvider } from '@/lib/i18n/client';

describe('Glosario en inglés', () => {
    it('mismas claves en los dos idiomas, todas con término y definición', () => {
        expect(Object.keys(glossaryEn).sort()).toEqual(Object.keys(glossary).sort());
        for (const entry of Object.values(glossaryEn)) {
            expect(entry.term.length).toBeGreaterThan(2);
            expect(entry.short.length).toBeGreaterThan(40);
        }
        expect(glossaryFor('es')).toBe(glossary);
        expect(glossaryFor('en')).toBe(glossaryEn);
    });

    it('etiquetas de moat según idioma (español por defecto)', () => {
        expect(moatLabel('switching_costs')).toBe('costes de cambio');
        expect(moatLabel('switching_costs', 'en')).toBe('switching costs');
        expect(moatLabel('brand', 'en')).toBe('brand and intangibles');
        expect(moatLabel('custom_moat_type', 'en')).toBe('custom moat type');
    });

    it('el término y el foso se pintan en el idioma elegido', () => {
        render(
            <LocaleProvider locale="en">
                <TooltipProvider>
                    <GlossaryTerm k="wacc" />
                    <MoatTerm type="network_effects" />
                </TooltipProvider>
            </LocaleProvider>,
        );
        expect(screen.getByText('WACC (weighted average cost of capital)')).toBeTruthy();
        expect(screen.getByText('network effects')).toBeTruthy();
    });

    it('sin idioma elegido sigue en español', () => {
        render(<TooltipProvider><GlossaryTerm k="wacc" /></TooltipProvider>);
        expect(screen.getByText('WACC (coste medio ponderado de capital)')).toBeTruthy();
    });
});
