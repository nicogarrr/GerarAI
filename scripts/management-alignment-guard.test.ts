import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path: string) => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const service = read('data-engine/app/services/management_alignment.py');
const panel = read('components/research/sections/ManagementAlignmentSection.tsx');
const page = read('app/(root)/research/[ticker]/page.tsx');
const form4 = read('data-engine/app/services/connectors/form4.py');

test('new aggregation has no downloads, paid provider or protected analysis dependency', () => {
  assert.doesNotMatch(service, /\b(?:requests|httpx|urllib\.request|thesis_service|thesis_evidence_service|ticker_ownership_signals|dca_signal_service|valuation)\b/);
  assert.match(service, /db\.add\(record\)/);
  assert.match(service, /record = ManagementAlignmentSnapshot\(company_id=company\.id, tenant_id=db\.info\.get\("tenant_id"\)\)/);
  assert.doesNotMatch(service, /\b(?:fetch|post|send|delete|update)\(/);
  const actor = read('data-engine/app/workers/dramatiq_app.py').slice(read('data-engine/app/workers/dramatiq_app.py').indexOf('def recompute_management_alignment('));
  assert.doesNotMatch(actor, /(?:https?:\/\/(?:data\.|www\.)?sec\.gov|httpx\.|requests\.|thesis_service|dca_signal_service)/);
  assert.match(actor, /recompute_alignment\(db, company\)/);
  assert.match(service, /\*tenant_filters\(db, InsiderTransaction, InsiderFiling\)/);
  assert.match(service, /\*tenant_filters\(db, FinancialFact\)/);
  assert.match(service, /\*tenant_filters\(db, ManagementAlignmentSnapshot\)/);
});
test('snapshot availability is honest and GET does not calculate the signal', () => {
  const routes = read('data-engine/app/api/routes/companies.py');
  const route = routes.slice(routes.indexOf('@router.get("/{ticker}/management-alignment")'));
  assert.match(route, /data = read_alignment\(db, company\)/);
  assert.doesNotMatch(route, /recompute_alignment\(db/);
  assert.match(service, /"status": "pendiente"/);
  assert.match(service, /record\.version != VERSION/);
  assert.match(service, /payload\["stale"\]/);
  assert.match(read('data-engine/app/workers/scheduler.py'), /job_id="management_alignment_6h", hour="1,7,13,19"/);
});
test('signals stay next to credibility in Research, without a new tab or protected write path', () => {
  assert.match(page, /optionalSection\('directiva',[\s\S]{0,200}optionalSection\('incentivos', t\('research\.managementAlignment\.title'\)/);
  assert.doesNotMatch(panel, /MutationForm|Datos disponibles para tu análisis|Operaciones y fuentes del agregado/);
  assert.doesNotMatch(panel, /publicado |\(dato /);
  assert.match(panel, /row\.repurchases &&/);
  assert.match(panel, /row\.sbc_fcf_pct\.value !== null/);
  assert.doesNotMatch(panel, /(?:MutationForm|useEffect|fetch\(|server action|from .*actions)/);
  assert.doesNotMatch(read('lib/research/research-views.ts'), /incentivos/);
});
test('parser adds an explicit nullable flag without changing the shared legacy Boolean', () => {
  assert.match(form4, /node\.findtext\("transactionCoding\/aff10b5One"\)/);
  assert.match(form4, /\{"1": True, "true": True, "0": False, "false": False\}\.get\(raw\.strip\(\)\.lower\(\)\)/);
  assert.match(form4, /"rule_10b5_1": _rule_10b5_1\(node, footnotes\)/);
  assert.match(form4, /"alignment_10b5_1": alignment_plan_flag\(\s*node, root_flag=root\.findtext\("aff10b5One"\)/);
  assert.match(service, /plan = plan if type\(plan\) is bool else None/);
  assert.match(service, /t\["code"\] == "S" and t\["plan"\] is False/);
  assert.match(service, /if not groups\["unknown_sales"\]:/);
});
test('fallback is ordered, annual DEI is accession-anchored, and sources are mandatory', () => {
  assert.match(service, /metrics\.get\("shares_outstanding"\) or metrics\.get\("shares_diluted"\)/);
  assert.match(service, /allow_dei=fact\.accession_number in annual_year/);
  assert.match(service, /if not _url\(url\):\n        return None/);
  // SEC exige su fecha de depósito; ESEF/CNMV (filings.xbrl.org no la da) entran con la fecha en que ya eran públicos.
  assert.match(service, /if \(fact\.source_type == "SEC" and filed is None\) or known is None or known > today:/);
  assert.match(service, /"sources": \[a, b\]/);
  assert.match(service, /"repurchases_label": "Recompras \(bruto\)"/);
  assert.match(service, /"Dilución neta anual" if repurchases and issued else "Variación de acciones"/);
});
