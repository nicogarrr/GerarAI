import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('portada /api/news: dedupe de titulares literales y spam legal fuera (ficha conserva)', () => {
  const route = readFileSync('data-engine/app/api/routes/news.py', 'utf8');
  assert.ok(route.includes('exact_key'), 'la portada agrupa por clave de texto exacta normalizada');
  assert.ok(route.includes('find_group'), 'la portada une las noticias de una misma historia en un grupo');
  const cluster = readFileSync('data-engine/app/services/news_story_cluster.py', 'utf8');
  assert.ok(cluster.includes('def exact_key'), 'existe la clave de texto exacta');
  assert.ok(cluster.includes('group.text_key == text_key'), 'un titular literal repetido cae en el mismo grupo');
  assert.ok(route.includes('if ticker is None:'), 'dedupe y filtro de spam solo en la portada; la ficha de empresa muestra todo lo suyo');
  assert.ok(route.includes('is_law_firm_solicitation(original_headline(event), event.summary)'), 'el spam legal se filtra en lectura, sin borrar filas');
  assert.ok(route.includes('legal_solicitation'), 'la proyección legal_solicitation se conserva para la ficha');

  const clusterTests = readFileSync('data-engine/tests/test_news_story_cluster.py', 'utf8');
  assert.ok(clusterTests.includes('test_titular_literal_corto_sigue_dedupeado'), 'cubierto el titular literal corto');

  const tests = readFileSync('data-engine/tests/test_news_portada_dedupe_spam.py', 'utf8');
  assert.ok(tests.includes('test_portada_dedupa_titulares_literales'));
  assert.ok(tests.includes('test_portada_filtra_spam_legal'));
  assert.ok(tests.includes('test_ficha_empresa_conserva_spam_legal_etiquetado'));
});
