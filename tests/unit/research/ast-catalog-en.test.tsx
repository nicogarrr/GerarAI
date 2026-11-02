import { readFileSync } from 'node:fs';
import path from 'node:path';

import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it } from 'vitest';

import { AstOrbitPanel } from '@/components/research/AstOrbitPanel';
import { AST_DETERMINISTIC_PREFIX_ES, AST_USAGE_NOTE_ES } from '@/lib/research/ast-catalog-text';

// Las frases salen del backend: si cambian allí, este test lo dice.
const backend = (file: string) => readFileSync(path.resolve(__dirname, '../../../data-engine/app/services', file), 'utf8');

const aggregates = {
    count: 7, families: { SPACEMOBILE: 6, BLUEWALKER: 1 },
    epoch_min: '2026-10-29T08:00:00', epoch_max: '2026-10-30T12:00:00',
    inclination_deg_min: 53.0459, inclination_deg_max: 53.2, mean_motion_rev_day_min: 15.1, mean_motion_rev_day_max: 15.32, eccentricity_max: 0.000312,
};
// Lo que escribe _deterministic_analysis para esos agregados.
const summaryEs = 'Catálogo CelesTrak del grupo AST descargado el 2026-10-31T10:00:00+00:00: 7 objetos (1 BLUEWALKER, 6 SPACEMOBILE). Épocas orbitales entre 2026-10-29T08:00:00 y 2026-10-30T12:00:00. Inclinación entre 53.0459° y 53.2°, movimiento medio entre 15.1 y 15.32 rev/día, excentricidad máxima 0.000312.';
const analysis = {
    status: 'disponible', mode: 'determinista', generated_at: '2026-10-31T10:05:00+00:00',
    source: { name: 'celestrak', url: 'https://celestrak.org', fetched_at: '2026-10-31T10:00:00+00:00' },
    analysis: {
        summary: summaryEs,
        observations: [
            { text: 'Familias del catálogo: 1 BLUEWALKER, 6 SPACEMOBILE.' },
            { text: 'Época orbital más reciente: 2026-10-30T12:00:00; más antigua: 2026-10-29T08:00:00.' },
            { text: 'Inclinación entre 53.0459° y 53.2°; movimiento medio entre 15.1 y 15.32 rev/día.' },
        ],
        aggregates, llm_interpretation: null,
    },
} as never;
const data = { status: 'disponible', objects: [], fetched_at: '2026-10-31T10:00:00Z', cadence_hours: 2, usage_note: AST_USAGE_NOTE_ES, supgp: { status: 'sin_datos', objects: [], fetched_at: null } } as never;

describe('órbitas AST: nota de uso y lectura del catálogo en inglés', () => {
    beforeAll(() => {
        Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) });
    });

    it('el backend sigue mandando esas frases', () => {
        expect(backend('asts_catalog_service.py')).toContain(`"usage_note": "${AST_USAGE_NOTE_ES}"`);
        expect(backend('asts_llm_service.py')).toContain(`f"${AST_DETERMINISTIC_PREFIX_ES}{fetched_at}: "`);
    });

    it('con English sale en inglés, con las mismas cifras', () => {
        render(<AstOrbitPanel analysis={analysis} data={data} locale="en" />);
        expect(screen.getByText('Exploratory signal computed from orbital elements. BSTAR and derivatives are fit parameters, not telemetry or confirmation of deployment.')).toBeInTheDocument();
        expect(screen.getByText('CelesTrak catalog of the AST group downloaded on 2026-10-31T10:00:00+00:00: 7 objects (1 BLUEWALKER, 6 SPACEMOBILE). Orbital epochs between 2026-10-29T08:00:00 and 2026-10-30T12:00:00. Inclination between 53.0459° and 53.2°, mean motion between 15.1 and 15.32 rev/day, maximum eccentricity 0.000312.')).toBeInTheDocument();
        expect(screen.getByText('Catalog families: 1 BLUEWALKER, 6 SPACEMOBILE.')).toBeInTheDocument();
        expect(screen.getByText('Most recent orbital epoch: 2026-10-30T12:00:00; oldest: 2026-10-29T08:00:00.')).toBeInTheDocument();
        expect(screen.getByText('Inclination between 53.0459° and 53.2°; mean motion between 15.1 and 15.32 rev/day.')).toBeInTheDocument();
        expect(document.body.textContent).not.toMatch(/Señal|Catálogo|Familias|Época|Inclinación|movimiento medio/);
    });

    it('en castellano se pinta lo que manda el backend', () => {
        render(<AstOrbitPanel analysis={analysis} data={data} />);
        expect(screen.getByText(AST_USAGE_NOTE_ES)).toBeInTheDocument();
        expect(screen.getByText(summaryEs)).toBeInTheDocument();
        expect(screen.getByText('Familias del catálogo: 1 BLUEWALKER, 6 SPACEMOBILE.')).toBeInTheDocument();
    });

    it('una lectura del modelo (sin el prefijo determinista) no se toca', () => {
        const llm = { ...(analysis as object), mode: 'llm', analysis: { ...(analysis as { analysis: object }).analysis, summary: 'Model reading in English.', observations: [{ text: 'One note.' }] } } as never;
        render(<AstOrbitPanel analysis={llm} data={data} locale="en" />);
        expect(screen.getByText('Model reading in English.')).toBeInTheDocument();
        expect(screen.getByText('One note.')).toBeInTheDocument();
    });
});
