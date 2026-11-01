import { execFileSync } from "node:child_process";
import { e2eUiDatabasePath } from "./e2e-env";

/**
 * Semilla de precios locales para Browser E2E, SIN endpoint de aplicación.
 *
 * Los movers se calculan desde market_prices (tabla global, no tenant) de la
 * BD local del backend. En browser-e2e esa BD es un sqlite local al runner
 * (DATABASE_URL=sqlite:///./cavaai_ui_e2e.db, ver playwright.config.ts), así
 * que la semilla la escribe el propio test como fixture: ninguna superficie
 * firmada de la aplicación permite fabricar precios.
 *
 * Reglas honestas: la compañía debe existir (creada antes vía la API firmada
 * POST /api/companies/ensure, que es la vía real de provisioning); barra
 * plana (open=high=low=close); adj_close NULL porque la semilla no afirma
 * ajuste por splits/dividendos; upsert por (company_id, date) para poder
 * resembrar sin duplicar.
 */
export type SeedPriceRow = { date: string; close: number; volume?: number };

/**
 * `source` por defecto "e2e-fixture" (dato de apoyo: valoracion de cartera,
 * leyendas...). Los specs que siembran para los RANKINGS de movers deben
 * pasar "yfinance": es la unica fuente que el backend acepta como cierre
 * oficial (OFFICIAL_CLOSE_SOURCES en market_change.py) y con otra fuente el
 * universo sale vacio.
 */
export function seedMarketPrices(ticker: string, rows: SeedPriceRow[], source = "e2e-fixture"): void {
  const dbPath = e2eUiDatabasePath();
  const pythonBin = process.env.PYTHON_BIN ?? "python";
  const script = `
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1], timeout=30)
ticker = sys.argv[2].strip().upper()
row = db.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
if row is None:
    raise SystemExit(f"compania {ticker} no existe: crearla antes via POST /api/companies/ensure")
company_id = row[0]
for item in json.loads(sys.argv[3]):
    db.execute(
        "INSERT INTO market_prices (company_id, date, open, high, low, close, adj_close, volume, source, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, datetime('now'), datetime('now'))"
        " ON CONFLICT (company_id, date) DO UPDATE SET open=excluded.open, high=excluded.high,"
        " low=excluded.low, close=excluded.close, volume=excluded.volume, source=excluded.source",
        (company_id, item["date"], item["close"], item["close"], item["close"], item["close"], item.get("volume"), sys.argv[4]),
    )
db.commit()
`;
  execFileSync(pythonBin, ["-c", script, dbPath, ticker, JSON.stringify(rows), source], { stdio: "pipe" });
}
