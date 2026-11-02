import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { MaterialsLine } from '@/components/calendar/FollowedEarningsList';
import type { MaterialKind } from '@/lib/earnings-materials';
import { createTranslator } from '@/lib/i18n/translate';

// Etiquetas reales de cada documento del 8-K (KIND_LABEL de
// earnings_materials_service.py, leído del .py: si el backend las cambia, este test lo nota).
const PY = readFileSync('data-engine/app/services/earnings_materials_service.py', 'utf8');
const KIND_LABEL = Object.fromEntries(
    [...(PY.match(/KIND_LABEL = \{([^}]+)\}/)?.[1] ?? '').matchAll(/"(\w+)": "([^"]+)"/g)].map((m) => [m[1], m[2]]),
) as Record<MaterialKind, string>;
const KINDS: MaterialKind[] = ['nota_prensa', 'presentacion', 'documento'];
const documents = KINDS.map((kind, i) => ({ kind, label: KIND_LABEL[kind], exhibit: `EX-99.${i + 1}`, url: `https://sec.gov/${kind}` }));
const materials = { status: 'ok' as const, filed_at: '2026-10-20', filing_url: null, documents };

describe('MaterialsLine en inglés', () => {
    it('lee las tres etiquetas del backend', () => {
        expect(Object.keys(KIND_LABEL).sort()).toEqual([...KINDS].sort());
    });

    it('en inglés nombra cada documento en inglés, sin la etiqueta en castellano', () => {
        const { container } = render(<MaterialsLine materials={materials} ti={createTranslator('en')} />);
        expect(screen.getByRole('link', { name: 'Earnings release' })).toHaveAttribute('href', 'https://sec.gov/nota_prensa');
        expect(screen.getByRole('link', { name: 'Presentation' })).toHaveAttribute('href', 'https://sec.gov/presentacion');
        expect(screen.getByRole('link', { name: 'SEC document' })).toHaveAttribute('href', 'https://sec.gov/documento');
        for (const label of Object.values(KIND_LABEL)) expect(container.textContent).not.toContain(label);
    });

    it('en castellano sigue diciendo lo mismo que el backend', () => {
        render(<MaterialsLine materials={materials} />);
        for (const kind of KINDS) expect(screen.getByRole('link', { name: KIND_LABEL[kind] })).toBeInTheDocument();
    });

    it('un tipo que no conocemos se pinta con la etiqueta que llega', () => {
        const other = { ...materials, documents: [{ kind: 'otro' as MaterialKind, label: 'Anexo', exhibit: 'EX-99.9', url: 'https://sec.gov/x' }] };
        render(<MaterialsLine materials={other} ti={createTranslator('en')} />);
        expect(screen.getByRole('link', { name: 'Anexo' })).toBeInTheDocument();
    });
});
