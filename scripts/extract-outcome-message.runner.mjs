// Puente ejecutable para el guard: tsc no typecheca .mjs (allowJs off) y node
// con --experimental-strip-types resuelve la reexportación .ts transitivamente.
export { extractOutcomeMessage } from '../lib/actions/extract-outcome-message.ts';
