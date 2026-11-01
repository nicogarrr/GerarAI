/** Inversores: toda foto lleva autor, licencia libre y fuente; el archivo existe; sin foto = iniciales. */
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: explicit extension for node strip-types.
import { INVESTOR_PHOTOS } from '../app/(root)/inversores/_components/photos.ts';

const FREE = /^(Public domain|CC0|CC BY(-SA)? \d\.\d)$/;

test('cada foto tiene autor, licencia libre, fuente de Commons y archivo local', () => {
    const entries = Object.entries(INVESTOR_PHOTOS) as [string, Record<string, string>][];
    assert.ok(entries.length > 0);
    for (const [slug, photo] of entries) {
        assert.ok(photo.author.length > 0, `${slug}: autor`);
        assert.match(photo.license, FREE, `${slug}: licencia libre`);
        assert.match(photo.source, /^https:\/\/commons\.wikimedia\.org\/wiki\/File:/, `${slug}: fuente`);
        assert.ok(existsSync(`public${photo.src}`), `${slug}: archivo ${photo.src}`);
    }
});

test('el avatar usa la foto si existe y las iniciales si no', () => {
    const avatar = readFileSync('app/(root)/inversores/_components/Avatar.tsx', 'utf8');
    assert.match(avatar, /INVESTOR_PHOTOS\[slug\]/);
    assert.match(avatar, /NameAvatar/);
});

test('las pantallas con avatar pasan el slug', () => {
    // Carteras se fusiona en /inversores (decisión de Nico, 2026-10-20): quedan hub y ficha.
    for (const file of [
        'app/(root)/inversores/page.tsx',
        'app/(root)/inversores/[slug]/page.tsx',
    ]) {
        assert.match(readFileSync(file, 'utf8'), /<InvestorAvatar[^>]*slug=\{investor\.slug\}/, file);
    }
});

test('la ficha muestra la atribucion de la foto', () => {
    const ficha = readFileSync('app/(root)/inversores/[slug]/page.tsx', 'utf8');
    assert.match(ficha, /INVESTOR_PHOTOS\[investor\.slug\]/);
    assert.match(ficha, /Wikimedia Commons/);
});

test('la lista atribuye las fotos (title en la miniatura y nota al pie)', () => {
    assert.match(readFileSync('app/(root)/inversores/_components/Avatar.tsx', 'utf8'), /photoTitle=\{photo \? `\$\{t\('investors\.detail\.photo'\)\} \$\{photo\.author\}/);
    for (const file of ['app/(root)/inversores/page.tsx']) {
        assert.match(readFileSync(file, 'utf8'), /t\('investors\.hub\.photosNote'\)/, file);
    }
    assert.match(readFileSync('lib/i18n/messages/es/investors.json', 'utf8'), /Fotos con licencia libre de Wikimedia Commons/);
});
