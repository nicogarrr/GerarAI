/**
 * Guarda F146: el historial «Últimos disparos y entregas» de /alerts debe ser
 * trazable y accionable: hora del disparo visible y enlace a la investigación
 * cuando la alerta tiene ticker. Antes las tarjetas no mostraban hora ni
 * enlace pese a que la API ya entrega created_at y company_id.
 *
 * Ejecución: node --experimental-strip-types --test scripts/alerts-history-traceability-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const readSource = (rel: string) => readFileSync(join(root, rel), 'utf8');

describe('alerts history traceability guard (F146)', () => {
    it('la tarjeta de disparo muestra la hora del disparo', () => {
        const src = readSource('components/alerts/AlertsManager.tsx');
        // i18n: las etiquetas «Último disparo»/«Creada» viven en messages/<locale>/alerts.json.
        assert.ok(
            src.includes("ti('alerts.triggered.lastShot', { date: f.formatUserDateTime(item.triggeredAt) })"),
            'con triggeredAt se etiqueta «Último disparo»',
        );
        assert.ok(
            src.includes("ti('alerts.triggered.created', { date: f.formatUserDateTime(item.createdAt) })"),
            'sin triggeredAt (fila antigua) el fallback se etiqueta «Creada», nunca como disparo',
        );
    });

    it('la tarjeta enlaza a la investigación cuando hay ticker', () => {
        const src = readSource('components/alerts/AlertsManager.tsx');
        assert.ok(
            src.includes("href={alertThesisHref(item.ticker)}"),
            'el historial debe enlazar a la investigacion del ticker (pestaña tesis) cuando la alerta tiene ticker',
        );
        assert.ok(src.includes('item.ticker &&'), 'el enlace solo se muestra con ticker presente (nunca inventado)');
    });

    it('la acción frontend propaga el ticker que entrega la API', () => {
        const src = readSource('lib/actions/alerts.actions.ts');
        assert.ok(src.includes('ticker: row.ticker ?? null'), 'alerts.actions.ts debe propagar ticker');
        assert.ok(
            src.includes('triggeredAt: row.last_triggered_at ?? null'),
            'triggeredAt debe salir de last_triggered_at SIN fallback silencioso (null = desconocido, la UI etiqueta «Creada»)',
        );
        assert.ok(
            !src.includes('triggeredAt: row.last_triggered_at ?? row.created_at'),
            'fallback silencioso a created_at mostraria el PRIMER disparo como si fuera el ultimo',
        );
    });

    it('la API incluye ticker en ResearchAlertOut', () => {
        const schema = readSource('data-engine/app/schemas/api.py');
        const route = readSource('data-engine/app/api/routes/alerts.py');
        assert.ok(schema.includes('ticker: str | None = None'), 'ResearchAlertOut debe exponer ticker');
        assert.ok(route.includes('out.ticker = company.ticker if company else None'), 'list_alerts debe resolver el ticker');
        assert.ok(schema.includes('last_triggered_at: datetime | None'), 'ResearchAlertOut debe exponer last_triggered_at');
        const model = readSource('data-engine/app/models/entities.py');
        assert.ok(model.includes('last_triggered_at'), 'ResearchAlert debe persistir last_triggered_at');
        const service = readSource('data-engine/app/services/review_alert_service.py');
        assert.ok(
            service.includes('existing.last_triggered_at = now'),
            'un re-disparo por fingerprint debe actualizar last_triggered_at',
        );
        assert.ok(
            route.includes('desc(func.coalesce(ResearchAlert.last_triggered_at, ResearchAlert.created_at))'),
            'list_alerts debe ordenar por ultimo disparo real (fallback legacy created_at)',
        );
        const migration = readSource('data-engine/alembic/versions/0036_alert_last_triggered_at.py');
        assert.ok(
            !migration.includes('UPDATE research_alerts SET last_triggered_at'),
            'el backfill created_at -> last_triggered_at afirmaria una hora de ultimo disparo desconocida',
        );
    });
});
