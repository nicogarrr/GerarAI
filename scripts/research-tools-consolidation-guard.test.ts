import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
const page=readFileSync("app/(root)/research/page.tsx","utf8");
const nav=readFileSync("components/layout/SectionNav.tsx","utf8");
const constants=readFileSync("lib/constants.ts","utf8");
test("research tools have one contextual navigation, not an obsolete sidebar footer",()=>{
 assert.doesNotMatch(page,/dentro del grupo Research|title="Herramientas de research"|const TOOLS =|title="Contexto de cartera"/);
 // El subnav se DERIVA del ROUTE_CATALOG (campo hub): aqui ya no puede vivir
 // una tupla hardcodeada que se desincronice del resto de la navegacion.
 assert.doesNotMatch(nav,/\[.\/research\/workflows.,.Workflows.\]/);
 assert.doesNotMatch(constants,/\/research\/workflows/);
 // Contrato del e2e research-tools-consolidation: la raiz de Research se
 // anuncia «Empresas» en el subnav (subnavLabel) sin renombrar la miga.
 assert.match(constants,/subnavLabelKey: 'nav.items.empresas'/);
 assert.equal(JSON.parse(readFileSync("lib/i18n/messages/es/nav.json","utf8")).items.empresas,"Empresas");
 assert.match(nav,/t\(item\.subnavLabelKey\?\?item\.labelKey\)/);
});
