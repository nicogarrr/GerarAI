import assert from 'node:assert/strict';
import test from 'node:test';
import { ESLint } from 'eslint';

const eslint = new ESLint();
for (const filename of ['tests/browser/history-native-entries.cjs', 'scripts/check-example.mjs', 'components/Example.tsx']) {
  test(`React hook policy has its plugins in scope: ${filename}`, async () => {
    const config = await eslint.calculateConfigForFile(filename);
    for (const rule of ['error-boundaries', 'purity', 'set-state-in-effect']) {
      assert.equal(config.rules[`react-hooks/${rule}`][0], 1);
      assert.ok(config.plugins['react-hooks'].rules[rule]);
    }
    assert.ok(config.plugins.react.rules['no-unescaped-entities']);
  });
}
test('CommonJS is linted and hook rules actually execute, not ignored or disabled', async () => {
  const [result] = await eslint.lintText(
    'const React = require("react"); function Broken() { if (Math.random()) { React.useState(0); } return null; } module.exports = Broken;',
    { filePath: 'tests/browser/hook-policy-fixture.cjs' },
  );
  assert.ok(result.messages.some(message => message.ruleId === 'react-hooks/rules-of-hooks'), JSON.stringify(result.messages));
});
