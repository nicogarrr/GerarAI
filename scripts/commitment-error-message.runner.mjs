// Puente ejecutable para el guard: tsc no typecheca .mjs (allowJs off) y node
// con --experimental-strip-types resuelve la reexportación .ts transitivamente.
export { commitmentErrorMessage } from '../lib/actions/commitment-error-message.ts';
