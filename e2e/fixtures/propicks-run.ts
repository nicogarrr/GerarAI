import { execFileSync } from "node:child_process";
import { e2eUiDatabasePath } from "./e2e-env";

/**
 * Semilla de un run del embudo ProPicks para Browser E2E, SIN endpoint de
 * aplicación (mismo patrón que market-prices.ts / fx-rates.ts): la pagina
 * /propicks lee el ultimo run persistido via GET /api/propicks/runs y sin
 * run renderiza ProPicksLoadError, sin filtros ni Slider.
 *
 * Reglas honestas: el tenant y las companias deben existir (creados antes
 * via las llamadas firmadas del test); metrics/coverage van como {} — las
 * tarjetas muestran n/d donde no hay dato, nunca valores inventados.
 */
export type SeedProPicksCandidate = { ticker: string; rank: number; score: number };

export function seedProPicksRun(
  tenantExternalId: string,
  candidates: SeedProPicksCandidate[],
  asOf: string,
): void {
  const dbPath = e2eUiDatabasePath();
  const pythonBin = process.env.PYTHON_BIN ?? "python";
  const script = `
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1], timeout=30)
trow = db.execute("SELECT id FROM tenants WHERE external_id = ?", (sys.argv[2],)).fetchone()
if trow is None:
    raise SystemExit(f"tenant {sys.argv[2]} no existe: crearlo antes via una llamada firmada")
tenant_id = trow[0]
as_of = sys.argv[3]
cands = json.loads(sys.argv[4])
cur = db.execute(
    "INSERT INTO propick_runs (as_of, status, funnel_version, universe_size, passed_count, top_n, duration_ms, params, error, tenant_id, created_at, updated_at)"
    " VALUES (?, 'completed', 'e2e', ?, ?, ?, 1, '{}', NULL, ?, datetime('now'), datetime('now'))",
    (as_of, len(cands), len(cands), len(cands), tenant_id),
)
run_id = cur.lastrowid
for c in cands:
    crow = db.execute("SELECT id FROM companies WHERE ticker = ?", (c["ticker"],)).fetchone()
    if crow is None:
        raise SystemExit(f"compania {c['ticker']} no existe: crearla antes via POST /api/companies/ensure")
    db.execute(
        "INSERT INTO propick_candidates (run_id, company_id, passed, rank, score, failed_gates, metrics, coverage, tenant_id, created_at, updated_at)"
        " VALUES (?, ?, 1, ?, ?, '[]', '{}', '{}', ?, datetime('now'), datetime('now'))",
        (run_id, crow[0], c["rank"], c["score"], tenant_id),
    )
db.commit()
`;
  execFileSync(pythonBin, ["-c", script, dbPath, tenantExternalId, asOf, JSON.stringify(candidates)], { stdio: "pipe" });
}
