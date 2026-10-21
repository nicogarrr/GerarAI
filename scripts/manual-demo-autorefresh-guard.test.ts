/**
 * Guarda del auto-refresco de la valoración demo (pedido de Nico 21-oct-2026:
 * «No se actualiza sola»). La valoración mostrada se reconsulta sola, pero el
 * registro de operaciones sigue manual y el fanout al proveedor queda acotado.
 *
 * Ejecución: node --experimental-strip-types --test scripts/manual-demo-autorefresh-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const panel = readFileSync('components/paper-trading/ManualDemoPanel.tsx', 'utf8');

describe('auto-refresco de la valoración demo', () => {
    it('reutiliza la acción de valoración existente (sin endpoint ni fanout nuevo)', () => {
        assert.doesNotMatch(panel, /fetch\(|lib\/actions\//);
        assert.match(panel, /await refreshValuation\(\)/);
    });

    it('cadencia base de 60 s sin afirmar cuota de proveedor verificada', () => {
        assert.match(panel, /VALUATION_REFRESH_MS = 60_000/);
        assert.match(panel, /window\.setInterval\(tick, VALUATION_REFRESH_MS\)/);
        // Finnhub ≠ Yahoo de Mercados: la cuota del plan no se da por verificada.
        assert.match(panel, /la cuota del plan Finnhub NO está verificada/);
    });

    it('candado COMPARTIDO entre botón manual y auto, sin secuencia muerta', () => {
        // Un solo candado ref compartido; nada de contadores locales del efecto.
        assert.match(panel, /refreshLock = useRef\(\{ inFlight: false, failures: 0, lastStart: 0 \}\)/);
        assert.doesNotMatch(panel, /let inFlight = false/);
        assert.match(panel, /if \(lock\.inFlight\) return/);
        // Sin seq: el candado ya impide dos consultas en vuelo, así que una
        // respuesta vieja no puede pisar una nueva; un seq sería código muerto.
        assert.doesNotMatch(panel, /lock\.seq/);
        // El candado se libera siempre.
        assert.match(panel, /finally \{\s*lock\.inFlight = false/);
        // Manual y auto usan la MISMA ruta protegida.
        assert.match(panel, /startTransition\(\(\) => runRefresh\(\)\)/);
    });

    it('un clic durante una consulta no muere: botón deshabilitado y «Consultando…»', () => {
        // Busy real = transición del botón manual O consulta automática en vuelo.
        assert.match(panel, /const \[refreshing, setRefreshing\] = useState\(false\)/);
        assert.match(panel, /setRefreshing\(true\)/);
        assert.match(panel, /setRefreshing\(false\)/);
        assert.match(panel, /const refreshBusy = pending \|\| refreshing/);
        assert.match(panel, /pending=\{refreshBusy\}/);
        assert.match(panel, /disabled=\{refreshBusy\}/);
        assert.match(panel, /refreshBusy \? 'Consultando…'/);
    });

    it('puertas de sostenibilidad: visible, con posiciones, backoff exponencial ante fallos', () => {
        assert.match(panel, /document\.visibilityState !== 'visible' \|\| !due\(\)\) return/);
        assert.match(panel, /if \(!refreshValuation \|\| !hasPositions\) return/);
        // Backoff 60s×2^fallos con tope; reset en éxito real.
        assert.match(panel, /MAX_REFRESH_BACKOFF_MS = 16 \* 60_000/);
        assert.match(panel, /VALUATION_REFRESH_MS \* 2 \*\* lock\.failures/);
        assert.match(panel, /lock\.failures \+= 1/);
        // El listado US caído devuelve ok con filas N/D pero su fetch NO se
        // cachea server-side: reintentarlo cada 60 s quemaría fanout. La
        // acción lo señala de forma estructurada (listingUnavailable) y aquí
        // ese intento cuenta como fallo transitorio del backoff.
        assert.match(panel, /lock\.failures = result\.listingUnavailable \? lock\.failures \+ 1 : 0/);
        // Repuesta al volver a la pestaña respetando la espera vigente y
        // limpieza al desmontar (timer + listener).
        assert.match(panel, /visibilitychange/);
        assert.match(panel, /window\.clearInterval\(timer\)/);
        assert.match(panel, /document\.removeEventListener\('visibilitychange', onVisible\)/);
    });

    it('el botón manual se conserva como refresco inmediato y sin botón no-op', () => {
        assert.match(panel, /Actualizar cotizaciones|Consultar cotizaciones/);
        assert.match(panel, /onClick=\{onRefresh\}/);
        // Sin refreshValuation no se ofrece botón que no hace nada.
        assert.match(panel, /onRefresh=\{refreshValuation \? onRefresh : null\}/);
    });

    it('el copy ya no afirma que no se actualiza sola y sigue siendo honesto', () => {
        assert.doesNotMatch(panel, /No se actualiza sola/);
        assert.match(panel, /Se actualiza cada minuto mientras esta pestaña está visible/);
    });

    it('el registro de operaciones sigue manual: nada de autoprellenar fills con cotización', () => {
        const ticket = readFileSync('components/paper-trading/OrderTicket.tsx', 'utf8');
        assert.doesNotMatch(ticket, /setPrice\(.*quote|setPrice\(.*valuation|markPrice/i);
        assert.match(ticket, /no es una ejecución de\s+mercado/i);
    });
});
