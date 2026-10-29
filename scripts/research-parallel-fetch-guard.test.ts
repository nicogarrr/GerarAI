/**
 * Guard D2a: la ficha de research no puede volver a serializar sus lecturas.
 *
 * Un waterfall de red es invisible en los tests de comportamiento: la pagina
 * sigue pintando lo mismo de mas lento. Este guard mira el CODIGO y falla si
 * vuelve el patron:
 *
 *  1. `await` de una lectura de research dentro de un bucle sobre URLs.
 *  2. Lectura de la API de research sin AbortSignal/presupuesto (un fetch sin
 *     techo cuelga la funcion entera).
 *  3. `Promise.all` naked sobre llamadas degradables (un 503 lateral en una
 *     pagina en blanco).
 *  4. El presupuesto declarado desincronizado de `vercel.json`.
 *
 * Y sobre todo: CASOS NEGATIVOS. Un guard que no muerde no sirve, asi que aqui
 * se alimentan a proposito los tres antipatrones de vuelta y se comprueba que
 * el detector los VE. Si el detector se rompe, tambien falla el guard.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/research-parallel-fetch-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import * as parallel from '../lib/research/parallel-fetch.ts';
// @ts-expect-error TS5097
import * as telemetry from '../lib/research/fetch-telemetry.ts';

const {
  RESEARCH_RENDER_BUDGET_MS,
  RESEARCH_RENDER_MAX_DURATION_MS,
  degradedReasons,
  launchResearchBatch,
  pick,
  researchFailureReason,
  settleResearchBatch,
} = parallel;

const {
  dumpResearchTelemetry,
  enableResearchTelemetry,
  researchTelemetry,
  researchTelemetrySummary,
  resetResearchTelemetry,
  withResearchTelemetry,
} = telemetry;

const PAGE = readFileSync(new URL('../app/(root)/research/[ticker]/page.tsx', import.meta.url), 'utf8');
const VERCEL = JSON.parse(readFileSync(new URL('../vercel.json', import.meta.url), 'utf8')) as {
  functions: Record<string, { maxDuration?: number }>;
};

/* ------------------------------------------------------------------ *
 * Detectores. Cada uno recibe codigo y devuelve los hallazgos.
 * Se prueban con casos negativos mas abajo.
 * ------------------------------------------------------------------ */

/** Lecturas de la API de research que la ficha puede lanzar. */
const RESEARCH_READERS =
  /getResearch\w+|getMoatQualityScore|getCompanyMarketSnapshot|getWatchlist\(|getProfile\(|getAstOrbitOverview|askResearchCompanyChat/;

/**
 * (1) `await` dentro de un bucle: el antipatron clasico del fan-out secuencial.
 * Se busca el `for`/`for...of`/`while` y se comprueba si su cuerpo tiene un
 * `await` (que no este en un `Promise.all`).
 */
export function findSequentialLoopAwaits(source: string): string[] {
  const findings: string[] = [];
  const loop = /\b(for\s*\([^)]*\)|for\s+await\s*\([^)]*\)|for\s*\([^)]*\sof\b[^)]*\)|while\s*\()/g;
  let match: RegExpExecArray | null;
  while ((match = loop.exec(source)) !== null) {
    const body = source.slice(match.index, match.index + 400);
    // El await de un Promise.all SI es paralelo: no cuenta.
    const awaits = body.match(/await\s+\w+/g) ?? [];
    const parallel = body.match(/Promise\.all(?:Settled)?\s*\(/g) ?? [];
    if (awaits.length > parallel.length) {
      findings.push(`bucle en offset ${match.index} con await secuencial: ${match[0].trim()}`);
    }
  }
  return findings;
}

/**
 * (2) Lectura sin techo: una llamada a la API de research cuyo `await` no esta
 * ni dentro de un lote con presupuesto (`settleResearchBatch`, `viewData`,
 * `launchResearchBatch`) ni es un `await Promise.all`. Un fetch sin AbortSignal
 * cuelga la funcion entera hasta el `maxDuration`.
 */
export function findUnbudgetedReads(source: string): string[] {
  const findings: string[] = [];
  const pattern = /await\s+((?:getResearch\w+|getMoatQualityScore|getCompanyMarketSnapshot|getAstOrbitOverview|askResearchCompanyChat)\s*\()/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(source)) !== null) {
    const lineStart = source.lastIndexOf('\n', match.index) + 1;
    const line = source.slice(lineStart, source.indexOf('\n', match.index));
    const budgeted =
      /settleResearchBatch|launchResearchBatch|viewData\(|withResearchTelemetry\(|Promise\.all|\.settle\(\)/.test(line);
    if (!budgeted) findings.push(`lectura sin presupuesto en ${lineStart + 1}: ${line.trim()}`);
  }
  return findings;
}

/**
 * (3) `Promise.all` naked sobre lecturas degradables. Un `all` convierte un 503
 * de un widget lateral en una pagina en blanco; para eso esta `allSettled`.
 * Se excluye el `Promise.all` de `params`/`searchParams` (no son red).
 *
 * El `.catch` que degrada tiene que estar DENTRO de los argumentos del
 * `Promise.all` (aplicado a las llamadas del lote). Mirar una ventana de
 * caracteres alrededor dejaba que un `.catch` ajeno (otra promesa, un helper
 * posterior) absolviera al lote: `void algo.catch(...)` tras el `all` bastaba
 * para esconder un waterfall.
 */
function callArgsAt(source: string, open: number): string {
  let depth = 1;
  for (let i = open; i < source.length && i < open + 400; i += 1) {
    const ch = source[i];
    if (ch === '(') depth += 1;
    else if (ch === ')') {
      depth -= 1;
      if (depth === 0) return source.slice(open, i);
    }
  }
  return source.slice(open, Math.min(source.length, open + 400));
}

export function findNakedPromiseAll(source: string): string[] {
  const findings: string[] = [];
  const head = /Promise\.all\s*\(/g;
  let match: RegExpExecArray | null;
  while ((match = head.exec(source)) !== null) {
    const args = callArgsAt(source, match.index + match[0].length);
    if (!RESEARCH_READERS.test(args)) continue;
    if (!/\b(getResearch\w+|getMoatQualityScore|getCompanyMarketSnapshot|getAstOrbitOverview)\s*\(/.test(args)) continue;
    const readers = args.match(/get(?:Research\w+|MoatQualityScore|CompanyMarketSnapshot|AstOrbitOverview)\s*\(/g) ?? [];
    const catches = args.match(/\.catch\s*\(/g) ?? [];
    if (readers.length > catches.length) {
      findings.push(`Promise.all naked sobre lecturas degradables en offset ${match.index}`);
    }
  }
  return findings;
}

/* ------------------------------------------------------------------ *
 * Caso negativo: el detector tiene que ver los antipatrones.
 * ------------------------------------------------------------------ */

const ANTIPATRON_BUCLE = `
export async function ficha(ticker: string) {
  const endpoints = ['/a', '/b', '/c'];
  const out = [];
  for (const endpoint of endpoints) {
    out.push(await getResearchWorkspace(endpoint));
  }
  return out;
}`;

const ANTIPATRON_SIN_PRESUPUESTO = `
export async function ficha(ticker: string) {
  const model = await getResearchLongTermModel(ticker);
  const moat = await getResearchMoatWorkspace(ticker);
  return { model, moat };
}`;

const ANTIPATRON_ALL_NAKED = `
export async function ficha(ticker: string) {
  const [facts, metrics, thesis] = await Promise.all([
    getResearchFinancialsWorkspace(ticker),
    getResearchLongTermModel(ticker),
    getResearchThesisWorkspace(ticker),
  ]);
  return { facts, metrics, thesis };
}`;

const CODIGO_LIMPIO = `
export default async function ResearchCompanyPage({ params }) {
  const [resolved] = await Promise.all([params]);
  const viewTask = launchViewData(resolved.view, resolved.ticker);
  const viewPromise = viewTask ? settleResearchBatch([viewTask], RESEARCH_RENDER_BUDGET_MS) : Promise.resolve([]);
  const data = await viewData('thesis');
  return data;
}`;

describe('detectores: ven los antipatrones', () => {
  it('detecta el await secuencial en un bucle sobre URLs', () => {
    const found = findSequentialLoopAwaits(ANTIPATRON_BUCLE);
    assert.ok(found.length > 0, 'el detector debe marcar el for con await');
    assert.match(found[0]!, /bucle en offset/);
  });

  it('detecta lecturas sin AbortSignal ni presupuesto', () => {
    const found = findUnbudgetedReads(ANTIPATRON_SIN_PRESUPUESTO);
    assert.equal(found.length, 2, `deben marcarse las dos lecturas, came ${JSON.stringify(found)}`);
    assert.match(found.join('\n'), /getResearchLongTermModel/);
    assert.match(found.join('\n'), /getResearchMoatWorkspace/);
  });

  it('detecta el Promise.all naked sobre lecturas degradables', () => {
    const found = findNakedPromiseAll(ANTIPATRON_ALL_NAKED);
    assert.ok(found.length > 0, 'el detector debe marcar el Promise.all');
    assert.match(found[0]!, /Promise\.all naked/);
  });

  it('no marca el codigo que ya esta bien', () => {
    assert.deepEqual(findSequentialLoopAwaits(CODIGO_LIMPIO), []);
    assert.deepEqual(findUnbudgetedReads(CODIGO_LIMPIO), []);
    assert.deepEqual(findNakedPromiseAll(CODIGO_LIMPIO), []);
  });

  it('un Promise.all cuyo contenido ya va degradado con .catch si se tolera', () => {
    const degradado = `
async function ficha(ticker: string) {
  const [a, b] = await Promise.all([
    getCompanyMarketSnapshot(ticker).catch(() => null),
    getWatchlist().catch(() => []),
  ]);
  return { a, b };
}`;
    assert.deepEqual(findNakedPromiseAll(degradado), []);
  });

  it('un .catch AJENO tras el Promise.all no absuelve al lote (caso negativo)', () => {
    // El bug que tumbaba este detector: bastaba un `.catch` de cualquier otra
    // promesa dentro de la ventana de caracteres para declarar el lote
    // "ya degradado". El .catch tiene que estar sobre las llamadas del lote.
    const catchAgeno = `
export async function ficha(ticker: string) {
  const [facts, metrics] = await Promise.all([
    getResearchFinancialsWorkspace(ticker),
    getResearchLongTermModel(ticker),
  ]);
  void algo.catch(() => null); // .catch NO relacionado
  return { facts, metrics };
}`;
    const found = findNakedPromiseAll(catchAgeno);
    assert.equal(found.length, 1, `el .catch ajeno no debe esconder el Promise.all naked: ${JSON.stringify(found)}`);
  });
});

/* ------------------------------------------------------------------ *
 * La pagina real, que es lo que hay que proteger.
 * ------------------------------------------------------------------ */

describe('la ficha real no serializa sus lecturas', () => {
  it('sin await secuencial en bucles', () => {
    assert.deepEqual(findSequentialLoopAwaits(PAGE), []);
  });

  it('toda lectura de research pasa por el lote con presupuesto', () => {
    assert.deepEqual(findUnbudgetedReads(PAGE), []);
  });

  it('sin Promise.all naked sobre lecturas degradables', () => {
    assert.deepEqual(findNakedPromiseAll(PAGE), []);
  });

  it('el snapshot sigue siendo la UNICA lectura dura (el resto degrada)', () => {
    // Si esto cambia, alguien ha convertido un widget lateral en bloqueante.
    const hardReads = PAGE.match(/throw error;/g) ?? [];
    assert.ok(hardReads.length <= 2, 'solo el snapshot y el market de overview pueden propagar');
    assert.match(PAGE, /settleResearchBatch\(viewTasks, RESEARCH_RENDER_BUDGET_MS\)/);
    // El watchlist nunca tumba la ficha, pero tampoco miente: degrada a
    // "estado desconocido" (null, boton deshabilitado), no a una lista vacia
    // que pintaria "Seguir" aunque el usuario ya siga el ticker.
    assert.match(PAGE, /getWatchlist\(\)\)\.catch\(\(\) => null\)/);
    assert.doesNotMatch(PAGE, /getWatchlist\(\)\)\.catch\(\(\) => \[\]\)/);
  });

  it('la ficha no lanza el chat: la pregunta vive en el Cerebro', () => {
    assert.ok(!PAGE.includes('chatPromise'));
    assert.ok(!PAGE.includes('askResearchCompanyChat'));
  });

  it('cada lectura de research se lanza con telemetria o entra en el lote', () => {
    // Toda lectura de la ficha deja rastro: si aparece una sin `withResearch-
    // Telemetry` ni por el lote, el waterfall vuelve a ser invisible.
    const readers = PAGE.match(
      /(?:\bgetResearch\w+|\bgetMoatQualityScore|\bgetCompanyMarketSnapshot|\bgetAstOrbitOverview|\baskResearchCompanyChat)\s*\(/g,
    ) ?? [];
    const tracked = PAGE.match(/withResearchTelemetry\(/g) ?? [];
    assert.ok(readers.length > 0, 'debe haber lecturas que medir');
    assert.ok(
      tracked.length >= readers.length - 2,
      `lecturas sin telemetria: ${readers.length} lecturas, ${tracked.length} rastros (se toleran 2: el snapshot y el market, ya envueltos)`,
    );
  });
});

describe('el presupuesto declarado cuadra con el techo real', () => {
  it('RESEARCH_RENDER_MAX_DURATION_MS es el maxDuration de vercel.json', () => {
    const declared = VERCEL.functions['app/(root)/research/**']?.maxDuration;
    assert.equal(typeof declared, 'number', 'vercel.json debe declarar la funcion de research');
    assert.equal(RESEARCH_RENDER_MAX_DURATION_MS, (declared as number) * 1000);
  });

  it('el presupuesto de la pagina deja margen sobre el techo', () => {
    assert.ok(
      RESEARCH_RENDER_BUDGET_MS < RESEARCH_RENDER_MAX_DURATION_MS,
      'el presupuesto del lote tiene que ser menor que el techo de la funcion',
    );
    // Margen >= 50%: si se acerca al techo, el render de React se queda sin aire.
    assert.ok(
      RESEARCH_RENDER_BUDGET_MS * 2 <= RESEARCH_RENDER_MAX_DURATION_MS,
      `margen insuficiente: ${RESEARCH_RENDER_BUDGET_MS}ms contra ${RESEARCH_RENDER_MAX_DURATION_MS}ms`,
    );
  });
});

/* ------------------------------------------------------------------ *
 * Agregacion: N llamadas, K fallan -> N-K se usan y K degradan.
 * ------------------------------------------------------------------ */

describe('settleResearchBatch: K de N fallan sin romper la pagina', () => {
  it('N llamadas, K fallan: los N-K valores se usan y los K degradan con motivo', async () => {
    const entries = [
      { key: 'ok-1', promise: Promise.resolve('a') },
      { key: 'ko-1', promise: Promise.reject(new Error('503 del backend')) },
      { key: 'ok-2', promise: Promise.resolve('b') },
      { key: 'ko-2', promise: Promise.reject(new Error('timeout de 8000 ms')) },
      { key: 'ok-3', promise: Promise.resolve('c') },
    ];
    const settled = await settleResearchBatch(entries, 5000);
    assert.equal(settled.length, 5);
    assert.deepEqual(settled.filter((e) => e.ok).map((e) => (e as { value: string }).value), ['a', 'b', 'c']);
    const degraded = degradedReasons(settled);
    assert.equal(degraded.length, 2);
    assert.deepEqual(degraded.map((e) => e.key), ['ko-1', 'ko-2']);
    assert.match(degraded[0]!.reason, /503 del backend/);
    // Y la pagina los pinta igual: pick devuelve el N/D honesto.
    assert.equal(pick(settled, 'ko-1', 'N/D'), 'N/D');
    assert.equal(pick(settled, 'ok-2', 'N/D'), 'b');
  });

  it('un valor null legitimo no se confunde con un fallo', async () => {
    // Regresión: `drained === null` como centinela rompía lasCompany que no
    // tienen research y sí devuelven null.
    const settled = await settleResearchBatch([{ key: 'moat', promise: Promise.resolve(null) }], 5000);
    assert.equal(settled[0]!.ok, true);
    assert.equal(pick(settled, 'moat', 'N/D'), null);
  });

  it('una lectura colgada degrada por presupuesto sin tumbar a las demas', async () => {
    const colgada = new Promise<string>(() => {});
    const startedAt = Date.now();
    const settled = await settleResearchBatch(
      [
        { key: 'lenta', promise: colgada },
        { key: 'rapida', promise: Promise.resolve('ya') },
      ],
      60,
    );
    const elapsed = Date.now() - startedAt;
    assert.ok(elapsed < 1000, `el presupuesto no espera a la colgada (tardó ${elapsed}ms)`);
    // La rapida ya habia respondido: el presupuesto es POR ENTRADA, no sobre
    // el lote entero. Degradarla tambien seria perder un dato ya pagado.
    assert.deepEqual(settled.filter((e) => e.ok).map((e) => e.key), ['rapida']);
    assert.deepEqual(settled.filter((e) => !e.ok).map((e) => (e as { reason: string }).reason), ['timeout']);
    assert.equal(pick(settled, 'lenta', 'N/D'), 'N/D');
    assert.equal(pick(settled, 'rapida', 'N/D'), 'ya');
  });
});

describe('launchResearchBatch: abort y timeout son observables', () => {
  it('el signal del presupuesto aborta las lecturas que lo escuchen', async () => {
    let abortSignal: AbortSignal | undefined;
    const batch = launchResearchBatch(
      [
        {
          key: 'escucha',
          run: (signal) => {
            abortSignal = signal;
            return new Promise<string>((_resolve, reject) => {
              signal.addEventListener('abort', () => reject(signal.reason as Error));
            });
          },
        },
      ],
      50,
    );
    const settled = await batch.settle();
    assert.equal(settled[0]!.ok, false);
    assert.equal(researchFailureReason((settled[0] as { reason: unknown }).reason), 'abort');
    assert.ok(abortSignal?.aborted, 'la lectura recibe el signal abortado');
  });

  it('distingue timeout de cancelacion y de fallo de transporte', () => {
    assert.equal(researchFailureReason(new DOMException('x', 'TimeoutError')), 'timeout');
    assert.equal(researchFailureReason(new DOMException('x', 'AbortError')), 'abort');
    assert.equal(researchFailureReason(new Error('conexion rechazada')), 'conexion rechazada');
  });

  it('sin unhandledRejection aunque el lote se quede sin recoger', async () => {
    let unhandled = 0;
    const listener = () => { unhandled += 1; };
    process.on('unhandledRejection', listener);
    try {
      launchResearchBatch([{ key: 'rota', run: () => Promise.reject(new Error('500')) }], 5000);
      await new Promise((resolve) => setImmediate(resolve));
      await new Promise((resolve) => setImmediate(resolve));
      assert.equal(unhandled, 0, 'ningún rechazo del lote queda sin manejar');
    } finally {
      process.off('unhandledRejection', listener);
    }
  });
});

describe('telemetria por llamada', () => {
  it('mide duracion y resultado, y se puede volcar', async () => {
    resetResearchTelemetry();
    enableResearchTelemetry(false);
    await withResearchTelemetry('ok-endpoint', () => Promise.resolve(1));
    await assert.rejects(withResearchTelemetry('ko-endpoint', () => Promise.reject(new Error('boom'))));
    const samples = researchTelemetry();
    assert.equal(samples.length, 2);
    assert.equal(samples[0]!.endpoint, 'ok-endpoint');
    assert.equal(samples[0]!.ok, true);
    assert.equal(samples[1]!.ok, false);
    assert.match(samples[1]!.reason!, /boom/);
    const summary = researchTelemetrySummary();
    assert.equal(summary.length, 2);
    assert.equal(summary.find((e) => e.endpoint === 'ko-endpoint')?.failures, 1);
    assert.match(dumpResearchTelemetry(), /ko-endpoint calls=1 failures=1/);
    resetResearchTelemetry();
  });

  it('un fallo no se traga: el error se propaga intacto', async () => {
    resetResearchTelemetry();
    await assert.rejects(
      withResearchTelemetry('ko', () => Promise.reject(new Error('mensaje exacto'))),
      /mensaje exacto/,
    );
  });
});