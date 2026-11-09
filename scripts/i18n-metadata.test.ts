/**
 * Guardia del helper i18nPageMetadata (lib/i18n/metadata.ts): el patron
 * `const t = await getT(); return { title: t(k1), description: t(k2) };`
 * copiado en ocho paginas vive ahora en un solo sitio. Estructural porque
 * lib/i18n/server.ts depende de next/headers (no importable en node --test).
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const helper = readFileSync('lib/i18n/metadata.ts', 'utf8');

test('el helper mantiene la cadena original: getT, title y description', () => {
  assert.ok(helper.includes('export async function i18nPageMetadata('));
  assert.ok(helper.includes('const t = await getT();'));
  assert.ok(helper.includes('return { title: t(titleKey), description: t(descriptionKey) };'));
  assert.ok(helper.includes("from './server.ts'"));
});

const pages: Array<[string, string, string]> = [
  ['app/(root)/mercados/page.tsx', 'markets.metaTitle', 'markets.metaDescription'],
  ['app/(root)/cuellos/page.tsx', 'bottlenecks.page.metaTitle', 'bottlenecks.page.metaDescription'],
  ['app/(root)/temas/page.tsx', 'themes.page.metaTitle', 'themes.page.metaDescription'],
  ['app/(root)/inversores/page.tsx', 'investors.hub.title', 'investors.hub.description'],
  ['app/(root)/inversores/aprender/page.tsx', 'investors.learn.metaTitle', 'investors.learn.description'],
  ['app/(root)/inversores/canales/page.tsx', 'investors.channels.title', 'investors.channels.description'],
  ['app/(root)/inversores/cartas/page.tsx', 'investors.letters.metaTitle', 'investors.letters.metaDescription'],
  ['app/(root)/inversores/cartas/[id]/page.tsx', 'investors.reader.metaTitle', 'investors.reader.metaDescription'],
];

for (const [file, titleKey, descriptionKey] of pages) {
  test(file + ' usa el helper con sus claves', () => {
    const src = readFileSync(file, 'utf8');
    const start = src.indexOf('generateMetadata');
    assert.ok(start >= 0, 'generateMetadata ausente');
    const block = src.slice(start, start + 220);
    assert.ok(
      block.includes('return i18nPageMetadata(\'' + titleKey + '\', \'' + descriptionKey + '\');'),
      'la pagina no llama al helper con sus claves',
    );
    assert.ok(!block.includes('{ title: t('), 'queda el objeto inline');
    assert.ok(src.includes("from '@/lib/i18n/metadata';"), 'falta el import del helper');
  });
}

const pages2: Array<[string, string, string]> = [
  ['app/(auth)/cuenta-pendiente/layout.tsx', 'auth.pendingAccount.metaTitle', 'auth.pendingAccount.metaDescription'],
  ['app/(auth)/sign-in/layout.tsx', 'auth.signIn.metaTitle', 'auth.signIn.metaDescription'],
  ['app/(auth)/sign-up/layout.tsx', 'auth.signUp.metaTitle', 'auth.signUp.metaDescription'],
  ['app/(root)/corporate-actions/page.tsx', 'corporateActions.meta.title', 'corporateActions.meta.description'],
  ['app/(root)/export/page.tsx', 'export.meta.title', 'export.meta.description'],
  ['app/(root)/risk/page.tsx', 'risk.meta.title', 'risk.meta.description'],
  ['app/(root)/search/page.tsx', 'search.title', 'search.metadataDescription'],
];

for (const [file, titleKey, descriptionKey] of pages2) {
  test(file + ' usa el helper con sus claves', () => {
    const src = readFileSync(file, 'utf8');
    const start = src.indexOf('generateMetadata');
    assert.ok(start >= 0, 'generateMetadata ausente');
    const block = src.slice(start, start + 220);
    assert.ok(
      block.includes('return i18nPageMetadata(\'' + titleKey + '\', \'' + descriptionKey + '\');'),
      'la pagina no llama al helper con sus claves',
    );
    assert.ok(!block.includes('{ title: t('), 'queda el objeto inline');
    assert.ok(src.includes("from '@/lib/i18n/metadata';"), 'falta el import del helper');
  });
}

test('los layouts de auth ya no importan getT sin usarlo', () => {
  for (const file of ['app/(auth)/cuenta-pendiente/layout.tsx', 'app/(auth)/sign-in/layout.tsx', 'app/(auth)/sign-up/layout.tsx']) {
    assert.ok(!readFileSync(file, 'utf8').includes('getT'), file + ' conserva getT');
  }
});
