/**
 * Guard del handoff de la guía de investigación unificada en el Cerebro
 * (PR #1526 + esta).
 *
 * Lo que protege, pieza a pieza:
 *  1. El contrato del evento `gerarai:open-brain` con detalle
 *     {ticker, question, review_id} (lib/brain/open-brain.ts).
 *  2. El redirect del antiguo /research/assistant: escribe el detalle en
 *     sessionStorage ANTES de navegar (sin carrera de efectos).
 *  3. El modo guía del Cerebro: con ticker llama a askResearchAssistantAction
 *     (POST /api/research/assistant) con ticker y review_id, y el cliente
 *     sigue cerrando en falso si writeback no es false (solo lectura).
 *  4. Que ningún enlace interno vuelve a apuntar a /research/assistant.
 *
 * Ejecutar: node --test scripts/brain-guide-handoff-guard.test.mjs
 */
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';

const openBrain = readFileSync('lib/brain/open-brain.ts', 'utf8');
const redirect = readFileSync('components/research/AssistantRedirect.tsx', 'utf8');
const brain = readFileSync('components/brain/GlobalBrain.tsx', 'utf8') + '\n' + readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');
const button = readFileSync('components/research/GuideBrainButton.tsx', 'utf8');
const seguir = readFileSync('components/research/GuideContextPanel.tsx', 'utf8');
const client = readFileSync('lib/research/assistant-client.ts', 'utf8');

test('1. contrato del handoff: evento, clave de sesión y detalle tipado', () => {
  assert.match(openBrain, /OPEN_BRAIN_PENDING_KEY = 'gerarai:open-brain:pending'/);
  assert.match(openBrain, /ticker\?: string;/);
  assert.match(openBrain, /question\?: string;/);
  assert.match(openBrain, /review_id\?: number;/);
});

test('2. el redirect escribe el handoff ANTES de navegar y conserva la revisión', () => {
  assert.match(redirect, /JSON\.stringify\(detail\)/);
  assert.match(redirect, /\.\.\.\(reviewId \? \{ review_id: reviewId \} : \{\}\)/);
  const write = redirect.indexOf('window.sessionStorage.setItem(OPEN_BRAIN_PENDING_KEY');
  const navigate = redirect.indexOf('router.replace(');
  assert.ok(write > -1, 'el redirect no escribe el handoff en sessionStorage');
  assert.ok(navigate > -1, 'el redirect no navega');
  assert.ok(write < navigate, 'el handoff debe escribirse antes del router.replace: si no, el Cerebro se monta sin detalle');
});

test('3. el Cerebro escucha el evento con detalle y consume el handoff de sesión', () => {
  assert.ok(brain.includes("window.addEventListener('gerarai:open-brain', openFromNavigation)"));
  assert.match(brain, /\(event as CustomEvent<OpenBrainDetail>\)\.detail/);
  assert.match(brain, /window\.sessionStorage\.getItem\(OPEN_BRAIN_PENDING_KEY\)/);
  assert.match(brain, /window\.sessionStorage\.removeItem\(OPEN_BRAIN_PENDING_KEY\)/);
});

test('3b. modo guía: ticker y review_id llegan al asistente de research (solo lectura)', () => {
  assert.match(brain, /await askResearchAssistantAction\(\{\s*mode: 'guide',\s*question: userMsg,\s*ticker: cleanTicker,\s*\.\.\.\(reviewId \? \{ review_id: reviewId \} : \{\}\),\s*page,\s*history,?\s*\}\)/);
  // Sin ticker el Cerebro NO llama al asistente: la guía es opt-in por el selector.
  assert.match(brain, /const cleanTicker = guideTicker\.trim\(\)\.toUpperCase\(\);\s*if \(cleanTicker\) \{/);
  // Fallo cerrado: un backend que no confirme writeback:false no se presenta como solo lectura.
  assert.match(client, /response\.writeback !== false/);
});

test('3c. los puntos de entrada despachan el detalle correcto', () => {
  // Ficha: «Guía de investigación» abre el Cerebro con el ticker.
  assert.match(button, /new CustomEvent\('gerarai:open-brain', \{ detail: \{ ticker \} \}\)/);
  // Pestaña Seguir: cada revisión abierta ancla su review_id.
  assert.match(seguir, /new CustomEvent\('gerarai:open-brain', \{ detail: \{ ticker, review_id: reviewId \} \}\)/);
});

test('4. ningún enlace interno apunta a /research/assistant (la página es un redirect)', () => {
  const offenders = [];
  const LINK = /(?:href=\{?["'`]|(?:router\.)?push\(\s*["'`])\/research\/assistant/;
  function walk(dir) {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules') continue;
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) { walk(full); continue; }
      if (!/\.(ts|tsx)$/.test(entry)) continue;
      if (LINK.test(readFileSync(full, 'utf8'))) offenders.push(full);
    }
  }
  for (const dir of ['app', 'components', 'lib', 'hooks']) walk(dir);
  assert.deepEqual(offenders, [], `enlaces internos al antiguo asistente: ${offenders.join(', ')}`);
});
