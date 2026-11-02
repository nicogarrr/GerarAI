/**
 * fetch() crudo a '/api/...' nunca apunta a una ruta inexistente.
 *
 * El contrato front-back lo vigila contract-drift.mjs, pero ese checker solo
 * ve las llamadas que pasan por los helpers (researchRequest/getJson/...).
 * Los fetch() crudos se le escapaban por los DOS extremos:
 *
 *  1. Navegador -> Next: `fetch('/api/companies/X/extended-quote')` en un
 *     componente pega contra el route handler de app/api/ (capa BFF), no
 *     contra FastAPI. Si ese route.ts no existe, el catch-all [...rest]
 *     devuelve un 404 JSON y la UI degrada en silencio.
 *  2. Route handler -> FastAPI: `fetch(`${BACKEND_URL}/api/thesis/X/epub`)`
 *     en un route.ts llama al data-engine SIN pasar por researchRequest:
 *     contract-drift no lo ve y una ruta renombrada en el backend romperia
 *     el handler en produccion sin que ningun check lo gritara.
 *
 * El matcher compara SEGMENTO A SEGMENTO y ANCLADO (misma cantidad de
 * segmentos salvo [...rest]), nunca por texto ni por prefijo:
 *   - Segmento de llamada estatico casa con segmento de ruta estatico
 *     identico o con uno dinamico ([param] Next / {param} OpenAPI):
 *     '/api/companies/KRKNF/extended-quote' casa con [ticker]/extended-quote.
 *   - Segmento de llamada con interpolacion (${...}) es un hueco que casa
 *     con CUALQUIER segmento de ruta, pero sigue contando como UN segmento:
 *     '/api/companies/${t}' NO casa con '/api/companies/[ticker]/extended-quote'
 *     (le sobra un segmento) ni con '/api/companies' (le falta uno).
 *   - Una interpolacion cuyo cuerpo contiene '?' es una QUERY CONDICIONAL
 *     (p.ej. `${recoverListing ? '?resolveListing=1' : ''}`): el path acaba
 *     justo antes y el match queda anclado — no es una cola libre.
 *   - '[...rest]' Next casa uno o mas segmentos finales.
 *
 * Las llamadas cuya URL no es un literal (fetch(url) con variable) no se
 * pueden auditar estaticamente. Las que existen (2026-10-31) estan auditadas
 * a mano y fijadas en DYNAMIC_KNOWN: todas o son a proveedores externos o
 * construyen el path desde literales que ya se verifico que existen. Una
 * llamada dinamica NUEVA (fichero nuevo o contador que crece) rompe el
 * guard; una que desaparece tambien (fail-closed: encoge la lista en el
 * mismo PR, como la baseline de find-dead-code).
 *
 * Ejecucion: node --experimental-strip-types --test scripts/raw-fetch-api-contract.test.ts
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = process.cwd();

function walk(dir: string, out: string[] = []): string[] {
    for (const entry of readdirSync(dir)) {
        if (entry === 'node_modules' || entry.startsWith('.') || entry === 'e2e' || entry === 'qa-e2e') continue;
        const full = join(dir, entry);
        if (statSync(full).isDirectory()) walk(full, out);
        else if (/\.(ts|tsx)$/.test(entry) && !/\.(test|spec|d)\.tsx?$/.test(entry)) out.push(full);
    }
    return out;
}

// --- Lado llamada: literal -> segmentos de path -----------------------------

type CallSeg = { kind: 'static'; text: string } | { kind: 'dynamic' };

/**
 * Convierte el literal crudo en segmentos de path anclados.
 * Devuelve tambien si el destino es el backend (URL absoluta o host
 * interpolado: `${BACKEND_URL}/api/...`) o Next (relativa '/api/...').
 */
function toCallSegs(raw: string): { segs: CallSeg[]; backend: boolean } | null {
    const backend = /^https?:\/\//.test(raw) || raw.startsWith('${');
    // Una interpolacion con '?' en el cuerpo es query condicional: el path
    // termina donde empieza ese ${...} (anclado, no cola libre).
    const holeRe = /\$\{([^}]*)\}/g;
    let end = raw.length;
    for (const m of raw.matchAll(holeRe)) {
        if (m[1].includes('?')) { end = m.index!; break; }
    }
    // Query estatica fuera de interpolaciones.
    const q = raw.slice(0, end).indexOf('?');
    if (q !== -1) end = q;
    let path = raw.slice(0, end);
    const i = path.indexOf('/api/');
    if (i === -1) return null;
    path = path.slice(i).replace(/\/+$/, '');
    const segs: CallSeg[] = path.split('/').filter((s) => s.length > 0).map((s) =>
        s.includes('${') ? { kind: 'dynamic' } : { kind: 'static', text: s },
    );
    return { segs, backend };
}

// --- Lado ruta: arbol Next y OpenAPI -> segmentos patron --------------------

type RouteSeg = { kind: 'static'; text: string } | { kind: 'param' } | { kind: 'rest' };

function parseRouteSegs(routePath: string): RouteSeg[] {
    return routePath.split('/').filter((s) => s.length > 0).map((s) => {
        if (/^\[\.\.\.[^\]]+\]$/.test(s)) return { kind: 'rest' };
        if (/^\[[^\]]+\]$/.test(s)) return { kind: 'param' };
        if (/^\{[^}]+\}$/.test(s)) return { kind: 'param' };
        return { kind: 'static', text: s };
    });
}

function nextRoutes(): { route: string; segs: RouteSeg[] }[] {
    const base = join(ROOT, 'app', 'api');
    const out: { route: string; segs: RouteSeg[] }[] = [];
    const walkRoutes = (dir: string): void => {
        for (const entry of readdirSync(dir)) {
            const full = join(dir, entry);
            if (statSync(full).isDirectory()) { walkRoutes(full); continue; }
            if (entry === 'route.ts' || entry === 'route.tsx') {
                const p = '/api/' + relative(base, dir).split('\\').join('/');
                const segs = parseRouteSegs(p);
                // El catch-all [...rest] es la red 404: casar SOLO con el ES
                // llamar a una ruta inexistente (esa es su funcion), asi que
                // nunca es destino valido de una llamada.
                if (segs.some((seg) => seg.kind === 'rest')) continue;
                out.push({ route: p, segs });
            }
        }
    };
    if (existsSync(base)) walkRoutes(base);
    return out;
}

function backendRoutes(): { route: string; segs: RouteSeg[] }[] {
    const spec = JSON.parse(readFileSync(join(ROOT, 'data-engine', 'openapi.json'), 'utf8'));
    return Object.keys(spec.paths ?? {}).map((p) => ({ route: p, segs: parseRouteSegs(p) }));
}

/** Match anclado segmento a segmento; 'rest' exige al menos un segmento. */
function routeMatches(call: CallSeg[], route: RouteSeg[]): boolean {
    let i = 0;
    let j = 0;
    while (j < route.length) {
        const r = route[j];
        if (r.kind === 'rest') return i < call.length; // 1+ segmentos
        if (i >= call.length) return false; // a la llamada le faltan segmentos
        const c = call[i];
        if (r.kind !== 'param' && c.kind !== 'dynamic' && r.kind === 'static' && r.text !== c.text) return false;
        i++;
        j++;
    }
    return i === call.length; // anclado: no puede sobrar ni faltar nada
}

function matchRoute(call: CallSeg[], routes: { route: string; segs: RouteSeg[] }[]): string | null {
    for (const r of routes) if (routeMatches(call, r.segs)) return r.route;
    return null;
}

// --- Extraccion de fetch() ---------------------------------------------------

type Call = { file: string; line: number; raw: string };

function rawFetchCalls(file: string): { calls: Call[]; dynamic: number } {
    const src = readFileSync(file, 'utf8');
    const calls: Call[] = [];
    let dynamic = 0;
    for (const m of src.matchAll(/\bfetch\(\s*/g)) {
        const rest = src.slice(m.index! + m[0].length);
        const q = rest[0];
        if (q !== '`' && q !== "'" && q !== '"') { dynamic++; continue; }
        const endIdx = rest.indexOf(q, 1);
        if (endIdx === -1) continue;
        const raw = rest.slice(1, endIdx);
        if (!raw.includes('/api/')) continue;
        calls.push({ file: relative(ROOT, file), line: src.slice(0, m.index).split('\n').length, raw });
    }
    return { calls, dynamic };
}

/**
 * Censo de fetch() con URL no literal, auditado a mano el 2026-10-31:
 *  - ObsidianVaultCard: VAULT_URL es la constante literal '/api/obsidian/vault.zip' (existe app/api/obsidian/vault.zip/route.ts).
 *  - export.actions: EXPORT_PATHS deriva '/api/export/{year}' (en OpenAPI).
 *  - privacy.actions: backendUrl() tipa el path como union de literales '/api/privacy/export' | '/api/privacy/account' (ambos en OpenAPI).
 *  - lib/research/zip-proxy: el helper de las rutas .zip (vault y tesis); path literal o con ticker, ambos en OpenAPI.
 *  - live-quotes, screener, newsSources, finnhub, propicksSignals: URLs de PROVEEDORES externos (Yahoo, Finnhub, FRED, stooq, Alpha Vantage, NewsAPI, Marketaux); ninguna toca '/api/'.
 */
const DYNAMIC_KNOWN: Record<string, number> = {
    'lib/research/zip-proxy.ts': 1,
    'components/export/ObsidianVaultCard.tsx': 1,
    'lib/actions/export.actions.ts': 1,
    'lib/actions/live-quotes.actions.ts': 1,
    'lib/actions/newsSources.actions.ts': 5,
    'lib/actions/privacy.actions.ts': 2,
    'lib/actions/screener.actions.ts': 1,
    'lib/upstream/finnhub.ts': 1,
    // boundedFetch de /api/logo: fetch a dominio EXTERNO (icono del sitio de la
    // empresa, validado por isSafeIconUrl en site-icon), nunca a /api/.
    'app/api/logo/[ticker]/route.ts': 1,
    'lib/utils/propicksSignals.ts': 1,
};

test('contrato: todo fetch() crudo a /api/ apunta a una ruta que existe', () => {
    const next = nextRoutes();
    const back = backendRoutes();
    assert.ok(next.length > 5, `arbol app/api sospechosamente pequeno (${next.length}): fallo cerrado`);
    assert.ok(back.length > 100, `OpenAPI sospechosamente pequeno (${back.length}): fallo cerrado`);

    const files = [...walk(join(ROOT, 'components')), ...walk(join(ROOT, 'hooks')), ...walk(join(ROOT, 'lib')), ...walk(join(ROOT, 'app'))];
    assert.ok(files.length > 50, 'barrido de ficheros sospechosamente pequeno: fallo cerrado');

    const misses: string[] = [];
    const dynamics = new Map<string, number>();
    let checked = 0;
    for (const f of files) {
        const { calls, dynamic } = rawFetchCalls(f);
        if (dynamic) dynamics.set(relative(ROOT, f), dynamic);
        for (const c of calls) {
            const parsed = toCallSegs(c.raw);
            if (!parsed) continue;
            checked++;
            const hit = matchRoute(parsed.segs, parsed.backend ? back : next);
            if (!hit) misses.push(`${c.file}:${c.line} -> ${parsed.backend ? 'FastAPI' : 'Next'} ${c.raw}`);
        }
    }
    assert.deepEqual(Object.fromEntries(dynamics), DYNAMIC_KNOWN,
        'fetch() con URL en variable fuera del censo auditado (o una conocida dejo de existir: encoge DYNAMIC_KNOWN en el mismo PR)');
    // 2026-11-01: las dos descargas del memo (.md y .pdf) comparten ahora un
    // unico fetch auditado en lib/thesis/fetch-memo.ts; eran 2 llamadas.
    assert.ok(checked >= 9, `solo ${checked} fetch crudos auditados (habia 9+ en 2026-11): fallo cerrado`);
    assert.deepEqual(misses, [], `fetch() a rutas inexistentes:\n${misses.join('\n')}`);
});

test('matcher: ruta inventada falla aunque el prefijo exista', () => {
    const next = nextRoutes();
    // Cola dinamica real: un segmento hueco NO abre la cola.
    assert.equal(matchRoute(toCallSegs('/api/companies/${ticker}/inventado')!.segs, next), null);
    // Un segmento de menos y un segmento de mas: anclado en ambos sentidos.
    assert.equal(matchRoute(toCallSegs('/api/companies/${ticker}')!.segs, next), null,
        'app/api/companies/[ticker] no tiene route.ts propio: un hueco no puede casar con prefijos mas largos');
    assert.equal(matchRoute(toCallSegs('/api/companies/${ticker}/extended-quote/extra')!.segs, next), null);
    assert.equal(matchRoute(toCallSegs('/api/definitivamente-no-existe')!.segs, next), null);
    assert.equal(matchRoute(toCallSegs('/api/definitivamente-no-existe')!.segs, backendRoutes()), null);
});

test('matcher: cola de parametro vs query condicional', () => {
    const next = nextRoutes();
    // Query condicional dentro de ${...}: el path acaba antes del hueco y el
    // match queda anclado a la ruta exacta (ni mas corta ni mas larga).
    const conQuery = toCallSegs("/api/companies/${encodeURIComponent(t)}/extended-quote${rec ? '?resolveListing=1' : ''}")!;
    assert.deepEqual(conQuery.segs, [
        { kind: 'static', text: 'api' },
        { kind: 'static', text: 'companies' },
        { kind: 'dynamic' },
        { kind: 'static', text: 'extended-quote' },
    ]);
    assert.equal(matchRoute(conQuery.segs, next), '/api/companies/[ticker]/extended-quote');
    // La misma ruta sin la query condicional: identico resultado.
    const sinQuery = toCallSegs('/api/companies/${encodeURIComponent(t)}/extended-quote')!;
    assert.equal(matchRoute(sinQuery.segs, next), '/api/companies/[ticker]/extended-quote');
    // Query estatica fuera de interpolacion tambien se corta.
    assert.equal(matchRoute(toCallSegs('/api/news/${id}/translation?lang=en')!.segs, next), '/api/news/[eventId]/translation');
});

test('matcher: ruta Next dinamica real casa con llamada estatica', () => {
    const next = nextRoutes();
    // [ticker] como PATRON: una llamada estatica casa con el segmento dinamico.
    assert.equal(matchRoute(toCallSegs('/api/companies/KRKNF/extended-quote')!.segs, next), '/api/companies/[ticker]/extended-quote');
    assert.equal(matchRoute(toCallSegs('/api/logo/PNG.V')!.segs, next), '/api/logo/[ticker]');
    // Backend: {param} igual, y fetch con ${BACKEND_URL} va contra el OpenAPI.
    // Con segmentos de llamada dinamicos varias rutas pueden ser compatibles
    // (un hueco casa tambien con un estatico como 'jobs'): el guard prueba
    // "existe alguna ruta compatible" (fail-open en la ambiguedad, fail-closed
    // en los estaticos, que es donde viven los renombrados). Por eso aqui se
    // aserta la compatibilidad con la ruta pretendida, no el orden de busqueda.
    const back = backendRoutes();
    const epub = toCallSegs('${BACKEND_URL}/api/thesis/${encodeURIComponent(t)}/epub')!;
    assert.ok(epub.backend);
    assert.ok(matchRoute(epub.segs, back), 'alguna ruta compatible existe');
    assert.ok(routeMatches(epub.segs, parseRouteSegs('/api/thesis/{ticker}/epub')));
    const feed = toCallSegs('https://engine.internal/api/calendar/feed/${token}.ics')!;
    assert.ok(feed.backend);
    assert.ok(routeMatches(feed.segs, parseRouteSegs('/api/calendar/feed/{filename}')));
    // El catch-all [...rest] NO tapa rutas inexistentes: es la red 404 y
    // casar solo con el es precisamente lo que el guard tiene que pillar.
    assert.equal(matchRoute(toCallSegs('/api/cualquier/cosa/larga')!.segs, next), null);
    assert.equal(matchRoute(toCallSegs('/api/companies/${ticker}/inventado-largo/profundo')!.segs, next), null);
});
