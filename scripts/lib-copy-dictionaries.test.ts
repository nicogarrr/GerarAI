import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097: Node strip-types needs explicit extensions.
import { corporateActionsEmptyMessage } from '../lib/research/corporate-actions-empty.ts';
// @ts-expect-error TS5097: Node strip-types needs explicit extensions.
import { formatPeerValue, peerMedianText } from '../lib/research/peer-format.ts';
// @ts-expect-error TS5097: Node strip-types needs explicit extensions.
import { analystTargetsNote } from '../lib/research/analyst-targets-copy.ts';
// @ts-expect-error TS5097: Node strip-types needs explicit extensions.
import { createTranslator } from '../lib/i18n/translate.ts';

test('helpers use the supplied request translator, not hardcoded copy', () => {
  const t = createTranslator('en');
  assert.equal(corporateActionsEmptyMessage(null, 'es', t), t('corporateActions.emptyState.noStatus'));
  assert.equal(formatPeerValue(null, 'roe', 'es', t), t('research.peerFormat.noData'));
  assert.equal(peerMedianText({ peer_median: null, insufficient_sample: true, note: 'n<7' }, 'roe', 'en', t), t('research.peerFormat.insufficientThreshold', { threshold: '7' }));
  for (const file of ['corporate-actions-empty', 'peer-format']) {
    const source = readFileSync(`lib/research/${file}.ts`, 'utf8');
    assert.doesNotMatch(source, /[?:]\s*['"`]Sin (?:eventos|datos)/);
  }
});

test('all analyst instrument codes resolve through explicit dictionary keys', () => {
  for (const locale of ['es', 'en'] as const) {
    const t = createTranslator(locale);
    for (const code of ['ETF', 'MUTUALFUND', 'INDEX', 'CURRENCY', 'CRYPTOCURRENCY', 'FUTURE', 'OPTION']) {
      const note = analystTargetsNote({ symbol: 'X', note_code: 'not_equity', instrument_type: code }, t);
      assert.equal(note, t('ui.analystTargets.notes.notEquity', { symbol: 'X', instrument: t(`ui.analystTargets.instrument.${code}` as Parameters<typeof t>[0]) }));
    }
    assert.equal(analystTargetsNote({ symbol: 'X', note: 'raw legacy' }, t), 'raw legacy');
  }
});
