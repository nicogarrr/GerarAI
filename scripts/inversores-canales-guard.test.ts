/** Canales de inversion: cada canal con URL https de YouTube, fuente y fecha; sin avatares copiados. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: explicit extension for node strip-types.
import { INVESTOR_CHANNELS, channelNoteLabel, channelSourceLabel } from '../app/(root)/inversores/canales/channels.ts';

const page = readFileSync('app/(root)/inversores/canales/page.tsx', 'utf8');
const list = readFileSync('app/(root)/inversores/_components/HubNav.tsx', 'utf8');

test('cada canal lleva URL de YouTube, fuente y fecha', () => {
    assert.ok(INVESTOR_CHANNELS.length >= 25);
    for (const channel of INVESTOR_CHANNELS) {
        assert.match(channel.url, /^https:\/\/www\.youtube\.com\/@[A-Za-z0-9._-]+$/, channel.name);
        assert.equal(channel.url, `https://www.youtube.com/${channel.handle}`);
        assert.ok(channel.source.length > 0, channel.name);
        // Pin de provenance: la fecha declarada debe ser una de las dos
        // tandas reales de verificacion y casar con la fecha de su fuente.
        assert.ok(['2026-10-06', '2026-10-11'].includes(channel.checked_at), channel.name);
        const sourceDate = channel.source.match(/\d{4}-\d{2}-\d{2}/);
        if (sourceDate) assert.ok(sourceDate[0] === channel.checked_at, channel.name);
    }
});

test('sin duplicados y las trampas de handle quedan fuera', () => {
    const urls = INVESTOR_CHANNELS.map((c: { url: string }) => c.url);
    assert.equal(new Set(urls).size, urls.length);
    for (const bad of ['@business', '@BloombergTelevision', '@AswathDamodaran']) {
        assert.ok(!urls.some((u: string) => u.endsWith(bad)), bad);
    }
});

test('las empresas van aparte y la pagina no copia avatares', () => {
    assert.ok(INVESTOR_CHANNELS.filter((c: { category: string }) => c.category === 'empresa').length === 5);
    assert.ok(!/<img|Image\b/.test(page));
});

test('el listado enlaza a los canales', () => {
    assert.match(list, /\/inversores\/canales/);
});

test('los canales generalistas van en negocio, no en inversion', () => {
    const byName = new Map(INVESTOR_CHANNELS.map((c: { name: string; category: string }) => [c.name, c.category]));
    assert.equal(byName.get('The Diary Of A CEO'), 'negocio');
    assert.equal(byName.get("Sourcery with Molly O'Shea"), 'negocio');
    assert.match(page, /category: 'negocio'/);
});

test('en inglés, fuente y nota de cada canal salen en inglés; en español, tal cual', () => {
    const spanish = /[áéíóúñ]|\b(de|del|la|el|en|y|cargada|capturas|sugerido|tema|probable|enlazado|economía)\b/i;
    for (const channel of INVESTOR_CHANNELS) {
        assert.equal(channelSourceLabel(channel.source), channel.source);
        assert.doesNotMatch(channelSourceLabel(channel.source, 'en').replace(/https:\/\/\S+/, ''), spanish, channel.name);
        if (channel.note) {
            assert.equal(channelNoteLabel(channel.note), channel.note);
            assert.doesNotMatch(channelNoteLabel(channel.note, 'en').replace('Jose Luis Cava', ''), spanish, channel.name);
        }
    }
    assert.match(page, /channelSourceLabel\(channel\.source, locale\)/);
    assert.match(page, /channelNoteLabel\(channel\.note, locale\)/);
});
