import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Teclado movil en campos identificador y numericos (Modern Web Guidance,
// forms.md): los campos que NO son prosa (tickers, emails de confirmacion)
// desactivan la correccion del teclado (autoCapitalize/autoCorrect/spellCheck)
// y los type="number" declaran inputMode="numeric" para que Android abra el
// teclado numerico directo. Sin esto iOS/Android autocorrigen tickers y
// muestran teclado completo en campos de solo digitos.

test('TickerSearchInput desactiva la correccion del teclado (identificador, no prosa)', () => {
    const source = readFileSync('components/search/TickerSearchInput.tsx', 'utf8');
    const input = source.slice(source.indexOf('<Input'), source.indexOf('>', source.indexOf('<Input')));
    assert.match(input, /autoCapitalize="none"/, 'falta autoCapitalize="none" en el buscador de tickers');
    assert.match(input, /autoCorrect="off"/, 'falta autoCorrect="off" en el buscador de tickers');
    assert.match(input, /spellCheck=\{false\}/, 'falta spellCheck={false} en el buscador de tickers');
});

test('los campos type="number" declaran inputMode="numeric"', () => {
    const cases = [
        ['app/(root)/search/page.tsx', 'name="collection_id"'],
        ['app/(root)/portfolio/intelligence/page.tsx', 'name="years"'],
        ['app/(root)/knowledge-graph/page.tsx', 'name="limit"'],
        ['components/research/sections/FinancialTerminalSection.tsx', 'name="years"'],
        ['components/research/ThesisHumanInputForm.tsx', 'name="fiscal_year"'],
        ['components/research/ResearchClaimForm.tsx', 'name="materiality_score"'],
        ['components/work-products/WorkProductDialog.tsx', 'id="wp-years"'],
    ];
    for (const [file, marker] of cases) {
        const source = readFileSync(file, 'utf8');
        const at = source.indexOf(marker);
        assert.ok(at >= 0, `${file}: no se encontro ${marker}`);
        const tag = source.slice(source.lastIndexOf('<', at), source.indexOf('>', at));
        assert.match(tag, /type="number"/, `${file}: ${marker} ya no es type="number" (revisa este guard)`);
        assert.match(tag, /inputMode="numeric"/, `${file}: ${marker} sin inputMode="numeric"`);
    }
});
