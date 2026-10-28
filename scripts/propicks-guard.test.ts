/**
 * Test ProPicks guard: sin datos futuros (as_of) y sin números inventados.
 *
 * Ejecución: node --experimental-strip-types --test scripts/propicks-guard.test.ts
 * (node:test estándar, sin dependencias nuevas ni cambios en package.json).
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
    validatePicks,
    validateNoFutureData,
    validateReasonsTraceable,
    validateNumbersTraceable,
    validateScoreFormula,
    validateOverlays,
    PROPICKS_SCORING_WEIGHTS,
    type PickLike,
    type OverlayLike,
// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types en runtime
} from '../lib/utils/propicksValidation.ts';
import {
    PROPICKS_STRATEGIES,
    selectRebalancedPicks,
// @ts-expect-error TS5097: la extensión .ts explícita la exige node --experimental-strip-types en runtime
} from '../lib/utils/proPicksStrategies.ts';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const readSource = (rel: string) => readFileSync(join(root, rel), 'utf8');

const NOW = new Date('2026-09-21T12:00:00.000Z');

/** Pick válido: todo número mostrado existe en facts y asOf <= ahora. */
function validPick(): PickLike {
    return {
        symbol: 'TEST',
        asOf: '2026-09-20T18:00:00.000Z',
        facts: {
            price: 100,
            targetMean: 120,
            upside: 20,
            return12M: 25,
            vsSP500: 8,
            cat_value: 80,
            cat_growth: 70,
            cat_profitability: 90,
            cat_cashFlow: 60,
            cat_momentum: 75,
            cat_debtLiquidity: 65,
        },
        confidenceReasons: [
            { metric: 'upside', value: 20, text: 'Potencial alcista del 20% (objetivo $120 vs $100)' },
            { metric: 'cat_profitability', value: 90, text: 'Rentabilidad 90/100 (+12 vs sector)' },
        ],
        currentPrice: 100,
        targetPrice: 120,
        upsidePotential: 20,
        // 80*.15+70*.20+90*.25+60*.15+75*.10+65*.15 = 74.75 → 75
        score: 75,
        categoryScores: {
            value: 80,
            growth: 70,
            profitability: 90,
            cashFlow: 60,
            momentum: 75,
            debtLiquidity: 65,
        },
    };
}

/** Overlay válido: metric volcada en facts como `ov_<metric>` y detail con el valor. */
function validOverlay(): OverlayLike {
    return {
        metric: 'analystMomentum',
        value: 12.5,
        detail: 'Momentum de analistas +12.5 (revisiones al alza)',
    };
}

/** Pick con overlay trazable (R5 en verde). */
function validPickWithOverlay(): PickLike {
    const pick = validPick();
    const overlay = validOverlay();
    pick.facts = { ...pick.facts, [`ov_${overlay.metric}`]: overlay.value };
    pick.overlays = [overlay];
    return pick;
}

describe('propicks-guard', () => {
    it('pick válido pasa las 4 reglas', () => {
        assert.deepEqual(validatePicks([validPick()], NOW), []);
    });

    it('R1: rechaza asOf futuro (datos futuros)', () => {
        const pick = validPick();
        pick.asOf = '2026-09-22T12:00:00.000Z';
        const issues = validateNoFutureData(pick, NOW);
        assert.equal(issues.length, 1);
        assert.equal(issues[0].rule, 'R1-as_of');
    });

    it('R1: rechaza pick sin asOf', () => {
        const pick = validPick();
        pick.asOf = '';
        assert.ok(validateNoFutureData(pick, NOW).length > 0);
    });

    it('R2: rechaza motivo con métrica ausente en facts (número inventado)', () => {
        const pick = validPick();
        pick.confidenceReasons = [
            ...pick.confidenceReasons,
            { metric: 'perMagico', value: 5, text: 'PER mágico de 5 (inventado)' },
        ];
        const issues = validateReasonsTraceable(pick);
        assert.ok(issues.some((i) => i.message.includes('perMagico')));
    });

    it('R2: rechaza motivo cuyo valor no coincide con facts', () => {
        const pick = validPick();
        pick.confidenceReasons = [
            { metric: 'upside', value: 99, text: 'Potencial alcista del 99% (falso)' },
            pick.confidenceReasons[1],
        ];
        assert.ok(validateReasonsTraceable(pick).length > 0);
    });

    it('R2: exige al menos 2 motivos trazables', () => {
        const pick = validPick();
        pick.confidenceReasons = [pick.confidenceReasons[0]];
        assert.ok(validateReasonsTraceable(pick).length > 0);
    });

    it('R3: rechaza upside incoherente con precio y objetivo', () => {
        const pick = validPick();
        pick.upsidePotential = 50; // real: (120-100)/100*100 = 20
        const issues = validateNumbersTraceable(pick);
        assert.ok(issues.some((i) => i.rule === 'R3-numeros'));
    });

    it('R3: rechaza currentPrice que no viene de facts/quotes', () => {
        const pick = validPick();
        pick.currentPrice = 10;
        assert.ok(validateNumbersTraceable(pick).length > 0);
    });

    it('R4: rechaza score que no reproduce la fórmula documentada', () => {
        const pick = validPick();
        pick.score = 10;
        const issues = validateScoreFormula(pick);
        assert.equal(issues.length, 1);
        assert.equal(issues[0].rule, 'R4-score');
    });

    it('pesos canónicos suman 1.0', () => {
        const total = Object.values(PROPICKS_SCORING_WEIGHTS).reduce((a, b) => a + b, 0);
        assert.ok(Math.abs(total - 1) < 1e-9, `suma = ${total}`);
    });

    it('SCORING_WEIGHTS del código coincide con los pesos canónicos', () => {
        const src = readSource('lib/utils/advancedStockScoring.ts');
        for (const [key, weight] of Object.entries(PROPICKS_SCORING_WEIGHTS)) {
            assert.ok(
                src.includes(`${key}: ${weight}`),
                `SCORING_WEIGHTS debe declarar ${key}: ${weight}`,
            );
        }
        assert.ok(src.includes('overallScore = round(') || src.includes('FÓRMULA DE SCORING'));
    });

    it('el action expone asOf, facts y confianza trazable', () => {
        const src = readSource('lib/actions/proPicks.actions.ts');
        for (const token of ['asOf', 'confidenceReasons', 'facts', 'confidenceLevel']) {
            assert.ok(src.includes(token), `proPicks.actions.ts debe contener ${token}`);
        }
    });

        it('UI en español con reintento', () => {
            const content = readSource('components/proPicks/EnhancedProPicksContent.tsx');
            const tabs = readSource('components/proPicks/ProPicksTabs.tsx');
            assert.ok(content.includes('Actualizar selección'));
            assert.ok(tabs.includes('Reintentar'));
        assert.ok(!content.includes('Regenerar Picks') || content.includes('Actualizar selección'));
    });
});

describe('propicks R5 (overlays)', () => {
    it('overlay trazable pasa R5 y validatePicks', () => {
        const pick = validPickWithOverlay();
        assert.deepEqual(validateOverlays(pick), []);
        assert.deepEqual(validatePicks([pick], NOW), []);
    });

    it('R5: rechaza overlay sin volcado en facts (ov_<metric>)', () => {
        const pick = validPick();
        pick.overlays = [validOverlay()]; // sin facts.ov_analystMomentum
        const issues = validateOverlays(pick);
        assert.equal(issues.length, 1);
        assert.equal(issues[0].rule, 'R5-overlays');
        assert.ok(issues[0].message.includes('ov_analystMomentum'));
    });

    it('R5: rechaza overlay cuyo valor difiere de facts (±0.51)', () => {
        const pick = validPickWithOverlay();
        assert.ok(pick.overlays);
        pick.overlays[0].value = 99; // facts dice 12.5
        const issues = validateOverlays(pick);
        assert.ok(issues.some((i) => i.rule === 'R5-overlays'));
    });

    it('R5: rechaza overlay cuyo detail no muestra el valor', () => {
        const pick = validPickWithOverlay();
        assert.ok(pick.overlays);
        pick.overlays[0].detail = 'Momentum de analistas al alza (sin cifra)';
        const issues = validateOverlays(pick);
        assert.ok(issues.some((i) => i.rule === 'R5-overlays' && i.message.includes('detail')));
    });

    it('R5: rechaza overlay sin metric', () => {
        const pick = validPickWithOverlay();
        pick.overlays = [{ metric: '', value: 1, detail: 'valor 1' }];
        const issues = validateOverlays(pick);
        assert.ok(issues.some((i) => i.rule === 'R5-overlays'));
    });

    it('R5: acepta métricas que ya traen el prefijo ov_ (sin duplicar)', () => {
        const pick = validPick();
        pick.facts = { ...pick.facts, ov_revisiones: 3.2 };
        pick.overlays = [{ metric: 'ov_revisiones', value: 3.2, detail: 'Sorpresa media +3.2% en 2 trimestres (valor 3.2)' }];
        assert.deepEqual(validateOverlays(pick), []);
        assert.deepEqual(validatePicks([pick], NOW), []);
    });
});

describe('propicks estrategias (value, momentum, defensiva)', () => {
    it('expone las 4 estrategias con pesos que suman 1.0', () => {
        const ids = PROPICKS_STRATEGIES.map((s) => s.id).sort();
        assert.deepEqual(ids, ['adaptive', 'defensiva', 'momentum', 'value']);
        for (const strategy of PROPICKS_STRATEGIES) {
            const total = Object.values(strategy.categoryWeights).reduce((a, b) => a + b, 0);
            assert.ok(Math.abs(total - 1) < 1e-9, `${strategy.id}: suma = ${total}`);
        }
    });

    it('value prima valor y rentabilidad (minScore 60)', () => {
        const strategy = PROPICKS_STRATEGIES.find((s) => s.id === 'value');
        assert.ok(strategy);
        assert.deepEqual(strategy.categoryWeights, {
            value: 0.35,
            growth: 0.05,
            profitability: 0.25,
            cashFlow: 0.15,
            momentum: 0.05,
            debtLiquidity: 0.15,
        });
        assert.equal(strategy.filters.minScore, 60);
    });

    it('momentum prima impulso y crecimiento (minScore 65)', () => {
        const strategy = PROPICKS_STRATEGIES.find((s) => s.id === 'momentum');
        assert.ok(strategy);
        assert.deepEqual(strategy.categoryWeights, {
            value: 0.10,
            growth: 0.25,
            profitability: 0.15,
            cashFlow: 0.10,
            momentum: 0.40,
            debtLiquidity: 0,
        });
        assert.equal(strategy.filters.minScore, 65);
    });

    it('defensiva prima rentabilidad y balance (minScore 65)', () => {
        const strategy = PROPICKS_STRATEGIES.find((s) => s.id === 'defensiva');
        assert.ok(strategy);
        assert.deepEqual(strategy.categoryWeights, {
            value: 0.15,
            growth: 0.05,
            profitability: 0.30,
            cashFlow: 0.20,
            momentum: 0.05,
            debtLiquidity: 0.25,
        });
        assert.equal(strategy.filters.minScore, 65);
    });
});

describe('propicks turnover cap (fixture determinista, sin red)', () => {
    const asOf = '2026-09-21T12:00:00.000Z';
    /** 35 candidatos con strategyScore 100..66 (rank S01 > S02 > … > S35). */
    const mkCandidates = (n: number) =>
        Array.from({ length: n }, (_, i) => ({
            symbol: `S${String(i + 1).padStart(2, '0')}`,
            score: 100 - i,
            strategyScore: 100 - i,
            asOf,
        }));

    it('top-20, mantiene incumbentes del top-30 y topa altas en 8', () => {
        const candidates = mkCandidates(35);
        const previous = ['S01', 'S02', 'S25', 'S26', 'S27', 'S28', 'S29', 'S30', 'S31', 'S32'];
        const out = selectRebalancedPicks(candidates, previous, asOf);
        const symbols = out.map((p) => p.symbol);
        // Incumbentes dentro del top-30 se mantienen…
        for (const kept of ['S01', 'S02', 'S25', 'S26', 'S27', 'S28', 'S29', 'S30']) {
            assert.ok(symbols.includes(kept), `${kept} debía mantenerse`);
        }
        // …los fuera del top-30 rotan.
        assert.ok(!symbols.includes('S31'), 'S31 (rank 31) debía rotar');
        assert.ok(!symbols.includes('S32'), 'S32 (rank 32) debía rotar');
        // Tope: 8 mantenidos + 8 altas nuevas = 16 (S03-S10).
        assert.deepEqual(symbols, [
            'S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08', 'S09', 'S10',
            'S25', 'S26', 'S27', 'S28', 'S29', 'S30',
        ]);
        assert.ok(out.length <= 20, `máx 20, hay ${out.length}`);
        const fresh = symbols.filter((s) => !previous.includes(s));
        assert.ok(fresh.length <= 8, `máx 8 altas nuevas, hay ${fresh.length}`);
        // Ordenados por strategyScore descendente y con asOf del rebalanceo.
        const scores = out.map((p) => p.strategyScore ?? p.score);
        assert.deepEqual([...scores].sort((a, b) => b - a), scores);
        assert.ok(out.every((p) => p.asOf === asOf));
    });

    it('bootstrap sin previous devuelve el top-20', () => {
        const out = selectRebalancedPicks(mkCandidates(35), [], asOf);
        assert.equal(out.length, 20);
        assert.deepEqual(
            out.map((p) => p.symbol),
            mkCandidates(20).map((p) => p.symbol),
        );
    });

    it('el action reexporta la selección con tope de rotación', () => {
        const actionSrc = readSource('lib/actions/proPicks.actions.ts');
        assert.ok(actionSrc.includes('selectRebalancedPicks'), 'proPicks.actions.ts debe reexportar selectRebalancedPicks');
        const stratSrc = readSource('lib/utils/proPicksStrategies.ts');
        for (const token of ['selectRebalancedPicks', 'previousSymbols']) {
            assert.ok(stratSrc.includes(token), `proPicksStrategies.ts debe contener ${token}`);
        }
    });
});

describe('propicks overlays en el action (contrato fuente)', () => {
    it('integra señales externas solo sobre finalistas con fallback', () => {
        const src = readSource('lib/actions/proPicks.actions.ts');
        for (const token of [
            'SignalOverlay',
            '@/lib/utils/propicksSignals',
            'getSignalOverlays',
            'Promise.allSettled',
            'attachSignalOverlays',
            'ov_',
            'overlayConfidenceDelta',
            'overlayFactsKey',
        ]) {
            assert.ok(src.includes(token), `proPicks.actions.ts debe contener ${token}`);
        }
    });

});

describe('F49: la fecha de ProPicks es la del run real, no la de carga', () => {
    it('la página no fabrica la fecha con new Date() y usa runAsOf del run', () => {
        const page = readSource('app/(root)/propicks/page.tsx');
        assert.ok(!page.includes('new Date().toISOString()'), 'page.tsx no debe fechar con la hora de carga');
        assert.ok(page.includes('generateEnhancedProPicksWithRun'), 'page.tsx debe leer runAsOf del run');
        assert.ok(page.includes('initialResult.runAsOf'), 'la fecha mostrada debe ser runAsOf');
    });

    it('el contenido no re-fecha tras aplicar filtros o reintentar', () => {
        const content = readSource('components/proPicks/EnhancedProPicksContent.tsx');
        assert.ok(!content.includes('new Date().toISOString()'), 'la fecha nunca es la hora del clic');
        assert.ok(content.includes('setLastGenerated(result.runAsOf)'), 'los refetch fijan la fecha del run');
    });

    it('el estado vacío distingue "sin run", "run sin candidatos aptos" y "filtros descartan"', () => {
        const content = readSource('components/proPicks/EnhancedProPicksContent.tsx');
        assert.ok(
            content.includes('El embudo todavía no ha publicado un run completado'),
            'sin run completado el estado vacío debe decirlo',
        );
        assert.ok(
            content.includes('no contiene candidatos que superen los criterios del embudo'),
            'run con passedCount=0: la culpa no es de los filtros',
        );
        assert.ok(
            content.includes('cumple los filtros actuales'),
            'con candidatos aptos, el estado vacío remite a los filtros actuales',
        );
        assert.ok(
            content.includes('passedCount === 0'),
            'la distinción debe venir de passedCount del run, no de suposiciones',
        );
    });

    it('generateEnhancedProPicksWithRun expone runAsOf y la variante simple lo reutiliza', () => {
        const actions = readSource('lib/actions/proPicks.actions.ts');
        assert.ok(actions.includes('runAsOf: funnel?.runAsOf ?? null'), 'el resultado debe exponer el runAsOf del embudo');
        assert.ok(actions.includes('passedCount: funnel?.passedCount ?? null'), 'el resultado debe exponer passedCount del embudo');
        assert.ok(
            actions.includes('const { picks } = await generateEnhancedProPicksWithRun(filters);'),
            'generateEnhancedProPicks debe delegar en la variante con run para no duplicar la lectura',
        );
    });
});
