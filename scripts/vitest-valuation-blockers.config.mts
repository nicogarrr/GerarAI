import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vitest/config';
export default defineConfig({
  resolve:{alias:{'@':fileURLToPath(new URL('..',import.meta.url))}},
  test:{environment:'node',include:['tests/unit/lib/research/valuation-blockers-preserve.test.ts'],
    coverage:{provider:'v8',include:['lib/research/valuation-blockers.ts'],reporter:['text','json-summary'],reportsDirectory:'coverage/valuation-blockers',thresholds:{perFile:true,lines:85,branches:85,functions:85,statements:85}}}
});
