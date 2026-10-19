import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard de «Escuchar la tesis»: <audio controls> arriba, junto a la cabecera
 * de la tesis, que lee la URL de audio por (ticker, versión). Sin Web Speech.
 */
const player = readFileSync('components/research/ThesisAudioPlayer.tsx', 'utf8');
const memo = readFileSync('components/research/ThesisMemo.tsx', 'utf8');
const route = readFileSync('app/api/thesis/[ticker]/audio/route.ts', 'utf8');

describe('audio de tesis', () => {
    it('es un <audio controls> con URL por ticker y versión, sin speechSynthesis', () => {
        assert.match(player, /<audio[^>]*controls/);
        assert.match(player, /\/api\/thesis\/\$\{encodeURIComponent\(ticker\)\}\/audio`/);
        assert.match(player, /\$\{base\}\?v=\$\{version\}/);
        assert.ok(!player.includes('speechSynthesis'));
        assert.ok(!player.includes('ningún texto sale'));
    });
    it('estados claros: sin audio no hay reproductor; pending se consulta; error reintenta', () => {
        assert.match(player, /state === 'ready' \?/);
        assert.match(player, /Generando audio…/);
        assert.match(player, /setTimeout\(tick, 5000\)/);
        assert.match(player, /No se pudo generar el audio\./);
        assert.match(player, /onError=\{\(\) => setState\('error'\)\}/);
    });
    it('va arriba de la tesis, antes del cuerpo y del memorando', () => {
        assert.ok(memo.includes('<ThesisAudioPlayer ticker={ticker} version={thesis.version} />'));
        assert.ok(memo.indexOf('<ThesisAudioPlayer') < memo.indexOf('Memorando completo'));
        assert.ok(memo.indexOf('<ThesisAudioPlayer') < memo.indexOf('executive_summary'));
    });
    it('el proxy valida ticker, firma la identidad, reenvía Range y expone POST y status', () => {
        assert.match(route, /requireAuthenticatedUser\(\)/);
        assert.match(route, /export const POST/);
        const status = readFileSync('app/api/thesis/[ticker]/audio/status/route.ts', 'utf8');
        assert.match(status, /audio\/status/);
        assert.match(route, /researchIdentityHeaders/);
        assert.match(route, /Range/);
    });
});
