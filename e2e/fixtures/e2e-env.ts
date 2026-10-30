import path from "node:path";

/**
 * Entorno de los e2e en UN sitio. Los valores por defecto son los del layout
 * de CI (backend en :8100, sqlite `data-engine/cavaai_ui_e2e.db`); fuera de CI
 * (otra máquina, otro puerto, otra BD) se cambian por variable de entorno sin
 * tocar los specs:
 *
 * - E2E_UI_BACKEND_URL   backend que usan el navegador y las semillas firmadas.
 * - E2E_UI_DATABASE_URL  DATABASE_URL del backend e2e (sqlite:///ruta). Relativa
 *                        = relativa a `data-engine/`, como la lee el backend.
 * - PYTHON_BIN           intérprete para las semillas directas en sqlite.
 * - E2E_REDIS_URL        REDIS_URL del backend e2e (broker y cachés). En CI hay
 *                        un Redis de servicio en localhost:6379; fuera de CI se
 *                        apunta a uno propio en vez de llenar el log de
 *                        «Connection refused».
 */
export const DEFAULT_E2E_UI_BACKEND_URL = "http://127.0.0.1:8100";
export const DEFAULT_E2E_UI_DATABASE_URL = "sqlite:///./cavaai_ui_e2e.db";

export const E2E_UI_BACKEND_URL = process.env.E2E_UI_BACKEND_URL || DEFAULT_E2E_UI_BACKEND_URL;
export const E2E_UI_DATABASE_URL = process.env.E2E_UI_DATABASE_URL || DEFAULT_E2E_UI_DATABASE_URL;
export const DEFAULT_E2E_REDIS_URL = "redis://localhost:6379/0";
export const E2E_REDIS_URL = process.env.E2E_REDIS_URL || DEFAULT_E2E_REDIS_URL;
export const E2E_PYTHON_BIN = process.env.PYTHON_BIN || "python3";

/** Ruta del fichero sqlite del backend e2e a partir de su DATABASE_URL. */
export function e2eUiDatabasePath(
  databaseUrl: string = E2E_UI_DATABASE_URL,
  repoRoot: string = process.cwd(),
): string {
  const match = /^sqlite:\/\/\/(.+)$/.exec(databaseUrl);
  if (!match) throw new Error(`E2E_UI_DATABASE_URL debe ser sqlite:///<ruta> (recibido: ${databaseUrl})`);
  const file = match[1];
  return path.isAbsolute(file) ? file : path.join(repoRoot, "data-engine", file);
}

/** Puerto del backend e2e (para arrancarlo en el mismo sitio que se espera). */
export function e2eUiBackendPort(url: string = E2E_UI_BACKEND_URL): string {
  return new URL(url).port || "8100";
}
