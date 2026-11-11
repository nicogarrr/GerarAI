import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const panels = readFileSync('components/research/FactsPanels.tsx', 'utf8');
const actions = readFileSync('lib/actions/research.actions.ts', 'utf8');

describe('cifras de la ficha enlazadas a su fuente', () => {
    it('el tipo ResearchFact declara la procedencia enlazable (nunca inventada)', () => {
        assert.ok(actions.includes('source_url?: string | null;'));
        assert.ok(actions.includes('source_title?: string | null;'));
        assert.ok(actions.includes('source_published_at?: string | null;'));
    });
    it('la fuente solo enlaza con URL real del backend', () => {
        // La procedencia visible vuelve en FactSource (#5300); la cifra
        // sigue enlazando, pero solo tras validar la URL del backend.
        assert.ok(panels.includes('function FactValueLink({ fact, children, locale }: { fact: ResearchFact; children: ReactNode; locale: Locale })'));
        assert.ok(panels.includes('const href = factSourceUrl(fact.source_url);'));
        assert.ok(panels.includes('if (!href) return <>{children}</>;'));
        assert.ok(panels.includes('href={href}'));
        assert.ok(!panels.includes('href={fact.source_url}'), 'no enlazar sin validar');
        assert.ok(panels.includes('rel="noopener noreferrer"'));
        assert.ok(panels.includes('target="_blank"'));
    });
    it('la cifra enlaza a su fuente en tabla de escritorio y en tarjeta móvil', () => {
        assert.ok(panels.includes('<FactValueLink fact={fact} locale={locale}>{metricValue(fact.value, fact.unit, locale)}</FactValueLink>'));
        assert.equal((panels.match(/<FactValueLink fact=\{fact\} locale=\{locale\}>/g) ?? []).length, 2, 'tarjeta móvil y tabla de escritorio');
    });
    it('sin documento de origen la cifra queda como texto plano', () => {
        // Sin URL solo texto; nunca un enlace ni URLs construidas a mano.
        const link = panels.slice(panels.indexOf('function FactValueLink'), panels.indexOf('export function FactCard'));
        assert.ok(link.includes('const href = factSourceUrl(fact.source_url);'));
        assert.ok(link.includes('if (!href) return <>{children}</>;'));
        assert.ok(link.includes('href={href}'));
        assert.ok(!link.includes('sec.gov/cgi-bin'), 'sin URLs construidas a mano');
    });
});
