/**
 * Guard de HONESTIDAD DE DIVISA del front (contrato de `lib/format.ts` L90-91:
 * «Una divisa ausente o rara NUNCA se sustituye por USD»).
 *
 * Por qué este guard y no otro: los tres guards de divisa que ya existían
 * (`market-panel`, `market-chart`, `research-portfolio`) son listas de
 * PROHIBIDOS por componente. Cinco sitios más se colaron por eso —la thesis, la
 * tabla de movimientos, la columna de precio del screener, las alertas y la
 * ficha DCF del inicio— y ninguno estaba cubierto. Este guard analiza el
 * CÓDIGO: recorre `app/`, `components/` y `lib/` y falla ante CUALQUIER moneda
 * inventada, con una lista de permitidos para lo que sí está justificado.
 *
 * Reglas que aplica (las cuatro del encargo):
 *   1. `formatMoney(...)` / `formatPrice(...)` con `'USD'` literal.
 *   2. `?? 'USD'` / `|| 'USD'` usado como divisa.
 *   3. `$` pegado a una interpolación (`$${valor}`): un símbolo de dólar
 *      escrito a mano en un texto de UI.
 *   4. Etiqueta o `aria-label` con un `(USD)` fijo: el input de alertas pedía
 *      un umbral en dólares para un valor que puede cotizar en cualquier
 *      divisa.
 *
 * Fuera de alcance, y por qué (para que nadie lo lea como un agujero):
 *   - `US$` EXPLÍCITO: legítimo cuando quien lo escribe declara de dónde sale el
 *     dato (market cap del screener, market cap de la watchlist para líneas US,
 *     KPIs del landing). Lo que se prohíbe es el DEFAULT silencioso, no el
 *     símbolo que anuncia la divisa de un dato verificado.
 *   - `currency = 'USD'` como valor por defecto de una prop: es la firma de
 *     `formatMoney`/`formatPrice` (`lib/format.ts` L108/L130) y de acciones cuyo
 *     backend también la exige. El default se corrige en el call site que lo
 *     ignora, no vetando la firma.
 *
 * Ejecución: node --experimental-strip-types --test scripts/currency-honesty-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_DIRS = ['app', 'components', 'lib'] as const;

function walk(dir: string): string[] {
    const found: string[] = [];
    for (const entry of readdirSync(join(root, dir), { withFileTypes: true })) {
        if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
        const relative = `${dir}/${entry.name}`;
        if (entry.isDirectory()) found.push(...walk(relative));
        else if (/\.(ts|tsx)$/.test(entry.name)) found.push(relative);
    }
    return found;
}

const FILES = SOURCE_DIRS.flatMap(walk).sort();

/** Analiza sobre el fuente con los blancos colapsados: una llamada partida en
 *  varias líneas no puede esconderse detrás de un regex por línea. `lineOf`
 *  traduce un índice del texto plano a su línea real (para el mensaje). */
function flatten(source: string): { text: string; lineOf: number[] } {
    let text = '';
    const lineOf: number[] = [];
    let line = 1;
    let index = 0;
    while (index < source.length) {
        const char = source[index];
        if (/\s/.test(char)) {
            let end = index;
            while (end < source.length && /\s/.test(source[end])) {
                if (source[end] === '\n') line += 1;
                end += 1;
            }
            text += ' ';
            lineOf.push(line);
            index = end;
            continue;
        }
        text += char;
        lineOf.push(line);
        index += 1;
    }
    return { text, lineOf };
}

const RULES = [
    {
        id: 'format-con-usd',
        re: /format(?:Money|Price)\([^)]{0,200}'USD'/g,
        why: "importe formateado con la divisa 'USD' fija: la cifra no puede ser de otra moneda",
    },
    {
        id: 'divisa-coalescida-a-usd',
        re: /(?:\?\?|\|\|)\s*'USD'/g,
        why: "divisa coalescida a 'USD': el backend sí la manda y se está sustituyendo",
    },
    {
        id: 'simbolo-dolar-en-texto',
        re: /\$\$\{/g,
        why: "símbolo de dólar escrito a mano junto a un valor interpolado",
    },
    {
        id: 'etiqueta-usd-fija',
        // Acotado a una etiqueta corta: `(USD)` dentro de un string de 60
        // caracteres es una etiqueta de input o un aria-label, no una coincidencia
        // lejana dentro de un bloque entero.
        re: /['"][^'"\n]{0,60}\(USD\)[^'"\n]{0,60}['"]/g,
        why: "etiqueta de input/aria-label con un '(USD)' fijo para un campo que admite cualquier divisa",
    },
] as const;

/**
 * Permitidos: cada uno es un fichero + un fragmento exacto que hay que
 * encontrar, con el porqué de por qué esa divisa SÍ está verificada. El fragmento
 * va porque un permiso por fichero entero dejaría pasar la regresión justo
 * detrás de él.
 */
const ALLOWED: Array<{ file: string; snippet: string; why: string }> = [
    {
        file: 'lib/format.ts',
        snippet: "currency = 'USD'",
        why: "Firma de formatMoney/formatPrice: el default vive en el helper y lo corrige el call site que lo ignora (vetar la firma sería vetar la API).",
    },
    {
        file: 'app/(root)/screener/page.tsx',
        snippet: "formatPrice(i.price, 'USD')",
        why: "F152: el backend etiqueta la serie (unit === 'usd': Bitcoin/oro/plata). Solo esa rama; un nivel de índice va como número plano.",
    },
    {
        file: 'components/insider/InsiderSignalsView.tsx',
        snippet: "formatPrice(value, 'USD', { minimumFractionDigits: 0, maximumFractionDigits: 0 })",
        why: "Form 4 / insider trading: el importe y la transacción se declaran y liquidan en USD ante la SEC (no hay divisa de bolsa que interpretar).",
    },
    {
        file: 'components/insider/InsiderOperationsView.tsx',
        snippet: "formatPrice(value, 'USD', { minimumFractionDigits: 2, maximumFractionDigits: 2 })",
        why: "Mismo bloque Form 4 que InsiderSignalsView/InsiderFeed: las operaciones insider se declaran y liquidan en USD ante la SEC; el precio medio lleva 2 decimales.",
    },
    {
        file: 'components/portfolio/EditTransactionDialog.tsx',
        snippet: "transaction.currency || 'USD'",
        why: "Semilla del SELECTOR de moneda del formulario de edición (editable por el usuario entre 9 divisas), no un importe pintado.",
    },

];

/** El permiso cubre el fragmento, no el fichero entero: el hallazgo cae
 *  permitido si el fragmento autorizado se SOLAPA con él (el regex puede empezar
 *  antes —`formatMoney(value: NumericInput, currency = 'USD'`— o después —
 *  `|| 'USD'`— según lo largo de la regla). */
function isAllowed(file: string, flat: string, matchIndex: number, matchLength: number): boolean {
    const matchEnd = matchIndex + matchLength;
    return ALLOWED.some((entry) => {
        if (entry.file !== file) return false;
        for (let at = flat.indexOf(entry.snippet); at >= 0; at = flat.indexOf(entry.snippet, at + 1)) {
            if (matchIndex < at + entry.snippet.length && at < matchEnd) return true;
        }
        return false;
    });
}


describe('honestidad de divisa (todo el front, no una lista de componentes)', () => {
    it('el universo del guard no está vacío (un glob roto pasaría en verde)', () => {
        assert.ok(FILES.length > 100, `solo ${FILES.length} ficheros analizados`);
    });

    it('ninguna moneda inventada fuera de la lista de permitidos', () => {
        const offences: string[] = [];
        for (const file of FILES) {
            const { text, lineOf } = flatten(readFileSync(join(root, file), 'utf8'));
            for (const rule of RULES) {
                rule.re.lastIndex = 0;
                for (let match = rule.re.exec(text); match !== null; match = rule.re.exec(text)) {
                    if (isAllowed(file, text, match.index, match[0].length)) continue;
                    offences.push(
                        `${file}:${lineOf[match.index] ?? 0} · ${rule.id} · ${rule.why}\n    ${match[0].slice(0, 120)}`,
                    );
                }
            }
        }
        assert.deepEqual(offences, [], `divisas inventadas:\n  ${offences.join('\n  ')}`);
    });

    it('cada permitido sigue existiendo y justificándose (sin permisos zombis)', () => {
        const stale = ALLOWED.filter((entry) => {
            const { text } = flatten(readFileSync(join(root, entry.file), 'utf8'));
            return !text.includes(entry.snippet);
        });
        assert.deepEqual(
            stale.map((entry) => `${entry.file}: ${entry.snippet}`),
            [],
            'permiso que ya no aplica: o el código se limpió (bórralo) o el fragmento se movió (actualízalo)',
        );
    });
});

describe('ThesisMemo: los importes de la tesis usan la divisa del listado', () => {
    const memo = readFileSync(join(root, 'components/research/ThesisMemo.tsx'), 'utf8');
    const page = readFileSync(join(root, 'app/(root)/research/[ticker]/page.tsx'), 'utf8');

    it('recibe la divisa y la valida (antes fijaba USD dentro de money())', () => {
        assert.ok(!/'USD'/.test(memo), 'ningún USD literal en la tesis');
        assert.match(memo, /isValidCurrencyCode\(currency\)/, 'la divisa se valida con el helper de lib/format');
        assert.match(memo, /currency\?: string \| null;/, 'la divisa entra como prop, no se supone');
        assert.match(memo, /if \(!isValidCurrencyCode\(currency\)\) return NA;/, 'sin divisa válida el importe es NA, nunca USD');
    });

    it('la página le pasa la divisa de la compañía, la misma que usa la valoración', () => {
        assert.match(page, /<ThesisMemo[\s\S]{0,200}currency=\{company\.currency\}/);
        assert.match(page, /<ValuationView[\s\S]{0,200}currency=\{company\.currency\}/);
    });

    it('todos los escenarios reciben la divisa (ninguna celda se queda sin moneda)', () => {
        const cells = memo.match(/<ScenarioCell[^>]*>/g) ?? [];
        assert.equal(cells.length, 5, 'las 5 celdas de escenario');
        for (const cell of cells) {
            assert.match(cell, /currency=\{currency\}/, `celda sin divisa: ${cell}`);
        }
    });
});

describe('PortfolioTransactions: la divisa la manda el ledger y el importe se declara', () => {
    const src = readFileSync(join(root, 'components/portfolio/PortfolioTransactions.tsx'), 'utf8');

    it('valida la divisa del movimiento en vez de coalescerla a USD', () => {
        assert.ok(!/(\?\?|\|\|)\s*'USD'/.test(src), 'sin divisa coalescida a USD');
        assert.match(src, /isValidCurrencyCode\(currency\)/, 'la divisa se valida con el helper de lib/format');
    });

    it('el backend no manda importe: el nocional va rotulado como bruto', () => {
        // /api/portfolio/transactions no expone total: el único número
        // derivable es cantidad x precio, que NO descuenta comisiones.
        const route = readFileSync(join(root, 'data-engine/app/api/routes/portfolio.py'), 'utf8');
        const payload = route.slice(route.indexOf('def _transaction_payload'), route.indexOf('@router.get("/summary"'));
        assert.ok(!/"(total|amount|notional)"/.test(payload), 'el backend sigue sin mandar importe por movimiento');
        assert.ok(/fees/.test(payload), 'las comisiones sí están en el ledger: por eso el importe va como «bruto»');
        assert.match(src, /const gross = tx\.quantity \* tx\.price;/, 'el nocional se deriva en un punto con nombre');
        // i18n: la etiqueta y la leyenda viven en messages/<locale>/portfolio.json.
        assert.match(src, /portfolio\.transactions\.grossTag/, 'el importe referencia la etiqueta «bruto» vía i18n');
        assert.match(src, /portfolio\.transactions\.grossNote/, 'la tarjeta referencia la leyenda vía i18n');
        const txEs = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/portfolio.json'), 'utf8'));
        assert.equal(txEs.transactions.grossTag, 'bruto', 'la etiqueta declara que no descuenta comisiones');
        assert.match(txEs.transactions.grossNote, /no descuenta las comisiones/, 'la leyenda de la tarjeta explica el alcance del importe');
    });
});

describe('alertas: el umbral no es un importe en dólares', () => {
    const src = readFileSync(join(root, 'components/alerts/AlertsManager.tsx'), 'utf8');

    it('el umbral se pinta sin símbolo y con la nota que declara el hueco', () => {
        assert.ok(!/\$\$\{/.test(src), 'nada de «$» pegado al valor');
        assert.match(src, /const threshold = f\.formatNumber\(value,/, 'el umbral se formatea con formatNumber, no con un $ pegado');
        // i18n: la nota vive en messages/<locale>/alerts.json; el código referencia la clave.
        assert.match(src, /alerts\.list\.thresholdNote/, 'la lista referencia la nota que declara el hueco');
        const alertsEs = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/alerts.json'), 'utf8'));
        assert.match(alertsEs.list.thresholdNote, /no guarda la divisa/, 'la nota declara que la regla no guarda la divisa');
    });

    it('el input no rotula una divisa que el usuario no puede elegir', () => {
        assert.ok(!/\(USD\)/.test(src), 'sin (USD) fijo en la etiqueta');
        // i18n: la etiqueta vive en messages/<locale>/alerts.json; el código referencia la clave.
        assert.match(src, /alerts\.form\.valuePrice/);
        const alertsEsForm = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/alerts.json'), 'utf8'));
        assert.match(alertsEsForm.form.valuePrice, /Precio \(divisa de la cotización\)/);
        // El input numérico precludes la coma decimal: el umbral es-ES
        // ("1522,60") llegaba vacío al parseo.
        assert.match(src, /type="text"/);
        assert.match(src, /inputMode="decimal"/);
        assert.ok(!/placeholder=\{[^}]*"100\.00"/.test(src), 'el placeholder es es-ES, no en-US');
    });
});

describe('screener: solo usa la divisa confirmada por el proveedor', () => {
    const page = readFileSync(join(root, 'app/(root)/screener/page.tsx'), 'utf8');
    const actions = readFileSync(join(root, 'lib/actions/screener.actions.ts'), 'utf8');

    it('formatea con divisa opcional y conserva número sin símbolo si falta', () => {
        assert.ok(!/formatPrice\(r\.price,\s*'USD'\)/.test(page));
        // El tipo de la fila vive en el contrato OpenAPI generado (alias): la
        // divisa sigue siendo opcional/anulable — solo la confirmada por el
        // proveedor — y se verifica en la fuente de verdad nueva.
        assert.ok(actions.includes("components['schemas']['ScreenerRealItemOut']"));
        const generated = readFileSync(join(root, 'lib/research/openapi.generated.ts'), 'utf8');
        const row = generated.slice(generated.indexOf('ScreenerRealItemOut: {'), generated.indexOf('ScreenerRealOut: {'));
        assert.match(row, /currency: string \| null/);
        assert.ok(page.includes('isValidCurrencyCode(currency)'));
        assert.ok(page.includes('formatPrice(price, currency)'));
        assert.ok(page.includes('screenerPrice(r.price, r.currency)'));
        assert.ok(!page.includes('backend no la expone'));
    });
});

describe('ficha DCF del inicio: el precio con la divisa del listado', () => {
    const src = `${readFileSync(join(root, 'components/PersonalizedOverview.tsx'), 'utf8')}\n${readFileSync(join(root, 'lib/actions/home-overview.actions.ts'), 'utf8')}`;

    it('precio y valor justo nunca caen al USD por defecto de formatMoney', () => {
        assert.ok(!/formatMoney\(op\.price\)/.test(src), 'el precio se formatea con su divisa o sin símbolo');
        assert.ok(!/formatMoney\(op\.fairValue\)/.test(src), 'el valor justo igual');
        assert.match(src, /currency: listing\.currency/, 'la divisa del precio viene del listado real (master)');
        assert.match(src, /getWatchlistEntryData\(sym\)/, 'precio y divisa salen de la MISMA fuente (nunca ticker desnudo)');
        assert.ok(!/getStockQuote\(/.test(src), 'getStockQuote no devuelve divisa: se cae en la línea US');
        assert.match(src, /home\.opportunities\.fairUnknown/, 'el valor justo declara la divisa que el modelo no propaga');
        const dictHome = JSON.parse(readFileSync(join(root, 'lib/i18n/messages/es/home.json'), 'utf8'));
        assert.ok(dictHome.opportunities.fairUnknown.startsWith('Valor justo (divisa'), dictHome.opportunities.fairUnknown);
    });
});
