import { execFileSync } from "node:child_process";
import path from "node:path";
import { e2eUiDatabasePath } from "./e2e-env";

/**
 * Semilla de tipos de cambio para Browser E2E, SIN endpoint de aplicación.
 *
 * fx_rates es una tabla por tenant de la BD local del backend (sqlite
 * cavaai_ui_e2e.db, ver playwright.config.ts). Sin filas USD->EUR el summary
 * de cartera devuelve status "incomplete_fx" con 0 holdings valoradas y la
 * página no renderiza gráficos: cualquier spec de UI de cartera con
 * posiciones en USD necesita esta semilla (mismo patrón que
 * e2e/fixtures/market-prices.ts).
 *
 * Reglas honestas: el tenant debe existir (lo crea la primera llamada
 * firmada del propio test); barra plana (misma tasa todas las fechas);
 * upsert por (base, quote, rate_date, tenant) para resembrar sin duplicar.
 */
export type SeedFxRow = { date: string; rate: number };

export function seedFxRates(
  tenantExternalId: string,
  baseCurrency: string,
  quoteCurrency: string,
  rows: SeedFxRow[],
): void {
  const dbPath = e2eUiDatabasePath();
  const pythonBin = process.env.PYTHON_BIN ?? "python";
  const script = `
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1], timeout=30)
row = db.execute("SELECT id FROM tenants WHERE external_id = ?", (sys.argv[2],)).fetchone()
if row is None:
    raise SystemExit(f"tenant {sys.argv[2]} no existe: crearlo antes via una llamada firmada")
tenant_id = row[0]
base = sys.argv[3].strip().upper()
quote = sys.argv[4].strip().upper()
for item in json.loads(sys.argv[5]):
    db.execute(
        "INSERT INTO fx_rates (base_currency, quote_currency, rate, rate_date, source, tenant_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'e2e-fixture', ?, datetime('now'), datetime('now'))"
        " ON CONFLICT (base_currency, quote_currency, rate_date, tenant_id) DO UPDATE SET rate=excluded.rate, source=excluded.source",
        (base, quote, item["rate"], item["date"], tenant_id),
    )
db.commit()
`;
  execFileSync(pythonBin, ["-c", script, dbPath, tenantExternalId, baseCurrency, quoteCurrency, JSON.stringify(rows)], { stdio: "pipe" });
}
