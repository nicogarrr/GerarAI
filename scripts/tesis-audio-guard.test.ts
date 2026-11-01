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
const audioEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).thesisAudio;

describe('audio de tesis', () => {
    it('es un <audio controls> con URL por ticker y versión, sin speechSynthesis', () => {
        assert.match(player, /<audio[^>]*controls/);
        assert.match(player, /\/api\/thesis\/\$\{encodeURIComponent\(ticker\)\}\/audio`/);
        assert.match(player, /\?version=\$\{version\}/);
        assert.match(player, /src=\{`\$\{base\}\$\{query\}`\}/);
        assert.ok(!player.includes('speechSynthesis'));
        assert.ok(!player.includes('ningún texto sale'));
    });
    it('estados claros: sin audio no hay reproductor; pending se consulta; error reintenta', () => {
        assert.match(player, /state === 'ready' \?/);
        assert.match(player, /t\('research\.thesisAudio\.generating'\)/);
        assert.match(audioEs.generating, /Generando audio…/);
        assert.match(player, /setTimeout\(tick, 5000\)/);
        assert.match(player, /t\('research\.thesisAudio\.failed'\)/);
        assert.match(audioEs.failed, /No se pudo generar el audio\./);
        assert.match(player, /onError=\{\(\) => setState\('error'\)\}/);
    });
    it('va arriba de la vista de tesis, con la última PUBLICADA (no el borrador) y antes de la tesis actual', () => {
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        assert.ok(!memo.includes('ThesisAudioPlayer'));
        const at = page.indexOf('<ThesisAudioPlayer');
        assert.ok(at > 0 && at < page.indexOf('id="tesis-actual"'));
        assert.match(page.slice(at, at + 400), /entry\.status === 'published'/);
    });
    it('sin tesis publicada se dice sin audio (no es un error) y el proxy reenvía ?version', () => {
        assert.match(player, /t\('research\.thesisAudio\.unpublished'\)/);
        assert.match(audioEs.unpublished, /Sin audio: aún no hay tesis publicada\./);
        assert.match(player, /hasKey === false/);
        assert.match(route, /\?version=/);
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
