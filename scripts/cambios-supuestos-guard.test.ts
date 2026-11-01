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
const feed = readFileSync('components/research/ChangesFeed.tsx', 'utf8');

describe('cambios y revisiones: qué supuesto toca y qué revisión queda', () => {
    it('la ficha monta el feed de cambios y el panel de revisiones abiertas sigue', () => {
        assert.match(page, /<ChangesFeed/);
        assert.match(feed, /dateTime\(c\.created_at\)/);
        assert.match(feed, /t\('research\.changesFeed\.reviewPending'\)/);
        assert.equal(JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).changesFeed.reviewPending, 'revisión pendiente');
        // QA 5: la vista declara fecha en cambios y alertas, como las demas vistas.
        assert.match(feed, /dateTime\(a\.created_at\)/);
        assert.match(feed, /event\.hasOpenReview \|\| event\.requiresReview/);
    });
});
