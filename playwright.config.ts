import { defineConfig } from "@playwright/test";
import { E2E_REDIS_URL, E2E_UI_BACKEND_URL, E2E_UI_DATABASE_URL, e2eUiBackendPort } from "./e2e/fixtures/e2e-env";

const runE2E = process.env.E2E_RUN === "1";
const runUiE2E = process.env.E2E_UI_RUN === "1";
const apiBaseURL = process.env.E2E_API_URL ?? "http://127.0.0.1:8101";
const uiBaseURL = process.env.E2E_UI_URL ?? "http://127.0.0.1:3100";
const uiPort = new URL(uiBaseURL).port || "3100";
const apiPort = new URL(apiBaseURL).port || "8101";
// Backend y BD del e2e de UI: e2e/fixtures/e2e-env.ts (mismos valores por
// defecto que CI, configurables por entorno para correr fuera de ese layout).
const uiBackendURL = E2E_UI_BACKEND_URL;
const e2eResearchSecret = process.env.RESEARCH_AUTH_SECRET ?? "cavaai-e2e-research-secret-at-least-32-characters";
const pythonBin = process.env.PYTHON_BIN ?? "python";
// La suite de flujos calienta las rutas de `next dev` antes del primer test
// (e2e/user-flows/global-setup.ts); el resto de suites no lo necesita.
const runUserFlows = runUiE2E && process.env.E2E_USER_FLOWS === "1";
export default defineConfig({
  testDir: "./e2e",
  // El repo arrastra GB de historial (snapshots versionados): el
  // gitCommitInfo por defecto de Playwright hace `git fetch origin <sha>`
  // acumulando stdout en memoria y el runner muere con
  // "RangeError: Invalid string length" antes de correr un solo test.
  captureGitInfo: { commit: false, diff: false },
  globalSetup: runUserFlows ? "./e2e/user-flows/global-setup.ts" : undefined,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  timeout: 90_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: runUiE2E ? uiBaseURL : apiBaseURL,
    trace: "retain-on-failure",
    // Las pruebas API firman por request (nonce unico, metodo/ruta/hash del
    // cuerpo) desde e2e/fixtures/research-api.ts; ya no hay HMAC global.
  },
  webServer: runUiE2E
    ? [
      {
        command: `${pythonBin} -m uvicorn main:app --host 127.0.0.1 --port ${e2eUiBackendPort()}`,
        cwd: "data-engine",
        env: {
          APP_ENV: "test",
          DATABASE_URL: E2E_UI_DATABASE_URL,
          RESEARCH_AUTH_REQUIRED: "true",
          RESEARCH_AUTH_SECRET: e2eResearchSecret,
          RESEARCH_AUTH_MAX_AGE_SECONDS: "3600",
          CAVAAI_ENABLE_VECTOR_INGEST: "0",
          CAVAAI_ENABLE_VECTOR_CHAT: "0",
          REDIS_URL: E2E_REDIS_URL,
          // E2E determinista: no depende de Finnhub/Yahoo ni de la red. El
          // endpoint responde vacío con `unavailable=true` y la UI muestra el
          // estado final honesto en lugar de "cargando" indefinidamente.
          SCREENER_QUOTE_VENDOR: "offline",
        },
        url: `${uiBackendURL}/health`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
      {
        command: `npm run dev -- --hostname 127.0.0.1 --port ${uiPort}`,
        env: {
          BETTER_AUTH_SECRET: process.env.BETTER_AUTH_SECRET ?? "cavaai-e2e-secret-at-least-32-characters",
          BETTER_AUTH_URL: uiBaseURL,
          // El bypass E2E exige APP_ENV=test de forma estricta (ver require-user.ts).
          APP_ENV: "test",
          E2E_AUTH_BYPASS: "1",
          FMP_BACKEND_URL: uiBackendURL,
          RESEARCH_AUTH_SECRET: e2eResearchSecret,
          NEXT_DIST_DIR: ".next-e2e",
        },
        url: `${uiBaseURL}/sign-in`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
    ]
    : runE2E
    ? {
        command: `${pythonBin} -m uvicorn main:app --host 127.0.0.1 --port ${apiPort}`,
        cwd: "data-engine",
        env: {
          APP_ENV: process.env.APP_ENV ?? "test",
          DATABASE_URL: process.env.DATABASE_URL ?? "sqlite:///./cavaai_e2e.db",
          RESEARCH_AUTH_REQUIRED: "true",
          RESEARCH_AUTH_SECRET: e2eResearchSecret,
          RESEARCH_AUTH_MAX_AGE_SECONDS: "3600",
          CAVAAI_ENABLE_VECTOR_INGEST: "0",
          CAVAAI_ENABLE_VECTOR_CHAT: "0",
          REDIS_URL: E2E_REDIS_URL,
        },
        url: `${apiBaseURL}/health`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : undefined,
});
