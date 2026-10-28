import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

const root = path.dirname(fileURLToPath(import.meta.url));

/**
 * Tests de comportamiento del frontend (Vitest + Testing Library + jsdom).
 *
 * Conviven con los guards `node --test` de scripts/*.test.ts: aquí se importa
 * el código real (funciones de lib/ y componentes de components/) y se
 * comprueba lo que hace, no cómo está escrito. Guía: docs/FRONTEND_TESTS.md.
 */
export default defineConfig({
    resolve: {
        alias: {
            '@': root,
            // 'server-only' solo se resuelve en el bundler de Next; en Vitest
            // se sustituye por un stub vacío para poder importar los módulos.
            'server-only': path.join(root, 'tests/unit/stubs/server-only.ts'),
        },
    },
    test: {
        environment: 'jsdom',
        include: ['tests/unit/**/*.test.{ts,tsx}'],
        setupFiles: ['tests/unit/setup.ts'],
        // Mismo huso que el job de CI de los guards de fechas: un test que pasa
        // solo en Europa/Madrid escondería un bug de día desplazado.
        env: { TZ: 'UTC' },
        restoreMocks: true,
        coverage: {
            provider: 'v8',
            // Se mide TODO lib/ y components/ (también lo que ningún test
            // importa, que cuenta como 0 %): el número es honesto, no el de los
            // ficheros que casualmente se cargaron.
            include: ['lib/**/*.{ts,tsx}', 'components/**/*.{ts,tsx}', 'middleware.ts'],
            exclude: ['**/*.d.ts', 'lib/research/openapi.generated.ts', 'lib/e2e-*.ts'],
            reporter: ['text-summary', 'json-summary', 'lcov'],
            reportsDirectory: 'coverage/frontend',
            // Trinquete: suelo = lo medido al introducir la suite (27-oct-2026:
            // líneas 2,71 %, sentencias 2,60 %, funciones 3,17 %, ramas
            // 1,76 %), redondeado a la baja con un pequeño margen. Es bajo
            // porque mide SOLO los tests de Vitest; la foto completa (con los
            // guards node:test) la da `npm run coverage:summary`. Solo se
            // sube, nunca se baja: ver docs/FRONTEND_TESTS.md.
            thresholds: {
                lines: 2.5,
                statements: 2.5,
                functions: 3,
                branches: 1.5,
            },
        },
    },
});
