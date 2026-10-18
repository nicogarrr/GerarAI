import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (p: string) => readFileSync(p, 'utf8');

test('cartas: biblioteca vacía ofrece descargar el corpus libre (actor, no relleno)', () => {
  const page = read('app/(root)/inversores/cartas/page.tsx');
  assert.ok(page.includes('IngestLettersButton'), 'la página de cartas debe usar IngestLettersButton en el estado vacío');
  assert.ok(page.includes('Todavía no hay cartas en la biblioteca.'));

  const button = read('app/(root)/inversores/_components/IngestLettersButton.tsx');
  assert.ok(button.includes('Descargar cartas gratuitas'));
  assert.ok(button.includes('bg-teal-600 text-white'), 'botón teal con texto blanco legible');
  assert.ok(button.includes('Descarga en curso'), 'confirma que la descarga quedó encolada');

  assert.ok(read('lib/actions/research-tools.actions.ts').includes('/api/knowledge/corpus/ingest-async'));
  const route = read('data-engine/app/api/routes/knowledge.py');
  assert.ok(route.includes('"/corpus/ingest-async"'));
  assert.ok(route.includes('ingest_letters_corpus.send('), 'la ruta encola el actor, no reimplementa la ingesta');

  const worker = read('data-engine/app/workers/dramatiq_app.py');
  assert.ok(worker.includes('def ingest_letters_corpus('), 'el actor existe en el worker');
  const service = read('data-engine/app/services/corpus_ingestion_service.py');
  assert.ok(service.includes('def ingest_free_corpus('), 'la lógica vive en el servicio (la usan actor y CLI)');
  assert.ok(service.includes('ingest_bytes('), 'dedupe SHA-256 vía KnowledgeLibraryService');
  assert.ok(read('data-engine/scripts/ingest_corpus.py').includes('ingest_free_corpus'), 'el CLI delega en el servicio');
});
