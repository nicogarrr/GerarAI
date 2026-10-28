import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard del seguimiento unido a la tesis (WorldStocks punto 2): cada cambio
 * muestra la revisión pendiente y qué toca (métricas/afirmaciones) usando
 * solo campos persistidos (affected_metrics, affected_claim_ids,
 * requires_review). Sin inferencia en cliente.
 */
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const card = readFileSync('components/research/ChangeImpactCard.tsx', 'utf8');
const feed = readFileSync('components/research/ChangesFeed.tsx', 'utf8');

describe('cambios y revisiones: qué supuesto toca y qué revisión queda', () => {
    it('marca la revisión pendiente en la tarjeta del cambio', () => {
        assert.match(card, /change\.requires_review \? <Badge>revisión pendiente<\/Badge> : null/);
    });
    it('nombra las métricas tocadas con su etiqueta en español', () => {
        assert.match(card, /change\.affected_metrics\.map\(\(metric\) => metricLabel\(metric\)\)/);
    });
    it('enlaza las afirmaciones afectadas con la tesis', () => {
        assert.match(card, /change\.affected_claim_ids\.length/);
        assert.match(card, /\?view=thesis/);
        assert.match(card, /Ver la tesis/);
    });
    it('sin campos persistidos no deduce nada: la línea no se pinta', () => {
        assert.match(card, /change\.affected_metrics\.length \|\| change\.affected_claim_ids\.length \? \(/);
    });
    it('la ficha monta la tarjeta y el panel de revisiones abiertas sigue', () => {
        assert.match(page, /<ChangesFeed/);
        assert.match(feed, /formatUserDateTime\(c\.created_at\)/);
        assert.match(feed, /revisión pendiente/);
        // QA 5: la vista declara fecha en cambios y alertas, como las demas vistas.
        assert.match(card, /formatUserDateTime\(change\.created_at\)/);
        assert.match(feed, /formatUserDateTime\(a\.created_at\)/);
        assert.match(feed, /event\.hasOpenReview \|\| event\.requiresReview/);
    });
});
