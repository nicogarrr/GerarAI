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
            // Trinquete: suelo ~1-2 puntos por debajo de lo medido en main
            // (31-oct-2026), con margen para el ruido entre corridas:
            // lineas 73,46 % (lcov, denominador 15215; algo mas tras los PRs
            // de tests de paper-trading y research-identity), sentencias
            // 72,05 %, funciones 70,74 %, ramas 65,47 % (union de shards con
            // reporter=json). Solo se sube, nunca se baja: ver
            // docs/FRONTEND_TESTS.md.
            thresholds: {
                lines: 73,
                statements: 71,
                functions: 69,
                branches: 64,
            },
        },
    },
});
