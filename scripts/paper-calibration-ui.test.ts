import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import type { PaperCalibration } from '../lib/actions/paper-trading.actions';

const payload: PaperCalibration = {
    base: 'retorno bruto > 0 al cierre; sin comisiones, FX ni dividendos',
    calculado_en: '2026-10-16T17:00:00Z', propuestas_llm: 50, cerradas_con_resultado: 30,
    muestra_insuficiente: false, minimo_cerradas: 30, aviso: null,
    brier: 0.1234, brier_referencia_sin_informacion: 0.25,
    bins: [{ rango: '0.50-0.75', cerradas: 5, conviction_media: 0.6, tasa_acierto: 0.8, hueco: 0.2, aviso: null }],
};
async function render(data?: PaperCalibration): Promise<string> {
    const ts = await import('typescript');
    const { createElement } = await import('react');
    const { renderToStaticMarkup } = await import('react-dom/server');
    const dir = 'node_modules/.cache/paper-calibration-render';
    mkdirSync(dir, { recursive: true });
    try {
        writeFileSync(`${dir}/view.mjs`, ts.transpileModule(readFileSync('components/proPicks/PaperCalibrationView.tsx', 'utf8'), {
            compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
        }).outputText
            // Alias @/ → fichero real (formato e idioma de lib/).
            .replace(/from '@\/([^']+)'/g, (_m, p) => `from '${pathToFileURL(`${process.cwd()}/${p}.ts`).href}'`));
        const mod = await import(`${process.cwd()}/${dir}/view.mjs`);
        return renderToStaticMarkup(createElement(mod.PaperCalibrationView, { data }));
    } finally { rmSync(dir, { recursive: true, force: true }); }
}
test('scoreboard calibration is consumed by the existing paper screen', () => {
    const view=readFileSync('components/proPicks/PaperTradingView.tsx','utf8');
    assert.match(view, /<PaperCalibrationView data=\{data.score.calibracion\}/);
    assert.match(readFileSync('lib/actions/paper-trading.actions.ts','utf8'), /calibracion\?: PaperCalibration/);
});
test('missing calibration is unavailable, never a manufactured zero', async () => {
    const html=await render(); assert.match(html,/Calibración no disponible/);assert.doesNotMatch(html,/Error Brier/);
});
test('shows Brier, reference and bins in Spanish, difference in points not returns', async () => {
    const html=await render(payload);for(const word of ['0,1234','0,25','80','60','20 p.p.','50 % - 75 %','30','50','No es una rentabilidad'])assert.ok(html.includes(word),word);
    assert.doesNotMatch(html,/Muestra insuficiente/);
});
test('empty or tiny sample keeps warning and missing bins rates', async () => {
    const html=await render({...payload,propuestas_llm:2,cerradas_con_resultado:2,muestra_insuficiente:true,aviso:'menos de 30 cerradas',brier:null,brier_referencia_sin_informacion:null,bins:[{rango:'0.00-0.50',cerradas:2,conviction_media:null,tasa_acierto:null,hueco:null,aviso:'menos de 5 cerradas: tasa N/D'}]});
    assert.match(html,/Muestra insuficiente/);assert.match(html,/no validan la capacidad predictiva/);assert.match(html,/menos de 5 cerradas/);assert.doesNotMatch(html,/NaN|Infinity/);
    assert.ok((html.match(/N\/D/g)??[]).length>=5);
});
test('zero Brier remains a real zero, non-finite remains N/D', async () => {
    const html=await render({...payload,brier:0,brier_referencia_sin_informacion:Number.NaN});
    assert.match(html,/Error Brier<\/dt><dd>0<\/dd>/);assert.match(html,/Referencia sin información<\/dt><dd>N\/D<\/dd>/);
});

test('real backend decimal bins become explicit percentages without changing values', async () => {
    const html=await render({...payload,bins:[{...payload.bins[0],rango:'0.00-0.10'}]});
    assert.match(html,/0 % - 10 %/);assert.doesNotMatch(html,/>0.00-0.10</);
});
