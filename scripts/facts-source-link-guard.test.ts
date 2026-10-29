import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const actions = readFileSync('lib/actions/research.actions.ts', 'utf8');

describe('cifras de la ficha enlazadas a su fuente', () => {
    it('el tipo ResearchFact declara la procedencia enlazable (nunca inventada)', () => {
        assert.ok(actions.includes('source_url?: string | null;'));
        assert.ok(actions.includes('source_title?: string | null;'));
        assert.ok(actions.includes('source_published_at?: string | null;'));
    });
    it('la fuente solo enlaza con URL real del backend y lleva fecha', () => {
        assert.ok(page.includes('function FactSource({ fact }: { fact: ResearchFact })'));
        assert.ok(page.includes('if (!fact.source_url) return <>{text}<FactCalculatedLabel fact={fact} /></>;'));
        assert.ok(page.includes("import { FactCalculatedLabel }"));
        assert.ok(page.includes('formatUserDate(fact.source_published_at)'));
        assert.ok(page.includes('rel="noopener noreferrer"'));
        assert.ok(page.includes('target="_blank"'));
    });
    it('la cifra enlaza a su fuente en tabla de escritorio y en tarjeta móvil', () => {
        assert.ok(page.includes('function FactValueLink({ fact, children }'));
        assert.ok(page.includes('<FactValueLink fact={fact}>{metricValue(fact.value, fact.unit)}</FactValueLink>'));
        assert.ok(page.includes('<FactSource fact={fact} />'));
    });
    it('sin documento de origen la fuente queda como texto plano', () => {
        // Sin URL solo texto y etiqueta Calculado; nunca un enlace.
        const factSource = page.slice(page.indexOf('function FactSource'), page.indexOf('function FactValueLink'));
        assert.ok(factSource.includes('label(fact.source_type)'));
        assert.ok(!factSource.includes('sec.gov/cgi-bin'), 'sin URLs construidas a mano');
    });
});
