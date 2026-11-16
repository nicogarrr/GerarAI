import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vitest/config';
export default defineConfig({
  resolve:{alias:{'@':fileURLToPath(new URL('..',import.meta.url))}},
  test:{environment:'node',include:['tests/unit/lib/research/thesis-text*.test.ts','tests/unit/research/source-basis-behavior.test.ts'],
    coverage:{provider:'v8',include:['lib/research/thesis-text.ts'],reporter:['text','json-summary'],reportsDirectory:'coverage/thesis-text',thresholds:{perFile:true,lines:85,branches:85,functions:85,statements:85}}}
});
