import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// El worker default cayo de forma permanente al fallback torch (103 % CPU,
// 2,13 GiB RSS + 1,2 GiB swap, medido por el piloto 5-nov-2026 02:22) porque
// la imagen horneaba solo el modelo de sentence-transformers: con
// HF_HUB_OFFLINE=1 y la cache de runtime vacia, fastembed no podia descargar
// MiniLM/bm25 jamas. Los modelos del carril caliente van horneados y el
// compose no puede re-apuntarlos a un volumen vacio.
const dockerfile = readFileSync('data-engine/Dockerfile.prod', 'utf8');
const compose = readFileSync('docker-compose.prod.yml', 'utf8');

test('la imagen hornea los modelos fastembed del carril caliente con ruta fija', () => {
  assert.match(dockerfile, /ENV FASTEMBED_CACHE_PATH=\/opt\/hf\/fastembed/);
  assert.match(dockerfile, /TextEmbedding\('sentence-transformers\/all-MiniLM-L6-v2'\)/);
  assert.match(dockerfile, /SparseTextEmbedding\('Qdrant\/bm25'\)/);
  // el pre-download corre antes de fijar HF_HUB_OFFLINE=1
  assert.ok(
    dockerfile.indexOf("TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')")
      < dockerfile.indexOf('ENV HF_HUB_OFFLINE=1'),
    'el pre-download de fastembed debe ir antes de HF_HUB_OFFLINE=1',
  );
});

const serviceBlock = (name: string) => {
  const start = compose.indexOf(`\n  ${name}:`);
  assert.ok(start > 0, `servicio ${name} no encontrado`);
  const rest = compose.slice(start + 1);
  const next = rest.search(/\n  [a-z][a-z0-9-]*:/);
  return next < 0 ? rest : rest.slice(0, next);
};

test('los carriles calientes (default y documents) no re-apuntan la cache a volumenes', () => {
  for (const name of ['worker', 'worker-documents']) {
    const block = serviceBlock(name);
    assert.ok(!block.includes('FASTEMBED_CACHE_PATH'), `${name} re-apunta FASTEMBED_CACHE_PATH`);
    assert.ok(!block.includes('HF_HOME'), `${name} re-apunta HF_HOME`);
  }
});

test('backend y worker-knowledge conservan su cache persistente (e5-large no horneado)', () => {
  assert.ok(serviceBlock('backend').includes('FASTEMBED_CACHE_PATH: /data/fastembed-cache'));
  const knowledge = serviceBlock('worker-knowledge');
  assert.ok(knowledge.includes('FASTEMBED_CACHE_PATH: /data/fastembed-cache'));
  assert.ok(knowledge.includes('HF_HOME: /data/hf-home'));
});
