import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";
import ts from "typescript";

const temp = mkdtempSync(`${tmpdir()}/atlas-test-`);
for (const name of ["letters", "investor-letters"]) {
  const source = readFileSync(
    `app/(root)/inversores/cartas/${name}.ts`,
    "utf8",
  ).replace(/(['"])\.\/letters\1/g, "'./letters.mjs'");
  writeFileSync(
    `${temp}/${name}.mjs`,
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.ESNext },
    }).outputText,
  );
}
const { investorLetters } = await import(
  pathToFileURL(`${temp}/investor-letters.mjs`).href
);
const conceptsSource = readFileSync(
  "app/(root)/inversores/conceptos/concepts.ts",
  "utf8",
);
writeFileSync(
  `${temp}/concepts.mjs`,
  ts.transpileModule(conceptsSource, {
    compilerOptions: { module: ts.ModuleKind.ESNext },
  }).outputText,
);
const { CONCEPTS, conceptsForInvestor } = await import(
  pathToFileURL(`${temp}/concepts.mjs`).href
);

const read = (file: string) => readFileSync(file, "utf8");
const letter = {
  id: 1,
  title: "Carta 2025",
  author: "Warren E. Buffett (Berkshire Hathaway)",
  document_type: "fund_letter",
  source_url: null,
  publication_date: "2025-02-20",
  status: "ready",
};
test("letters bind to exact known authors including ingestion identities", () => {
  assert.equal(investorLetters("buffett", [letter]).length, 1);
  assert.equal(
    investorLetters("quintana", [
      { ...letter, author: "Emérito Quintana (Numantia Patrimonio)" },
    ]).length,
    1,
  );
  for (const author of ["Charlie Munger", "Warren Buffett commentary", ""])
    assert.equal(investorLetters("buffett", [{ ...letter, author }]).length, 0);
  assert.equal(investorLetters("munger", [letter]).length, 0);
  assert.equal(
    investorLetters("buffett", [{ ...letter, status: "pending" }]).length,
    0,
  );
  assert.equal(
    investorLetters("buffett", [{ ...letter, document_type: "annual_report" }])
      .length,
    0,
  );
  assert.equal(investorLetters("unknown", [letter]).length, 0);
});
test("concepts have primary sources and do not attribute SEC education to an investor", () => {
  assert.equal(
    new Set(CONCEPTS.map((item: { slug: string }) => item.slug)).size,
    CONCEPTS.length,
  );
  assert.ok(
    CONCEPTS.every(
      (item: { source: { url: string }; risk: string; application: string }) =>
        item.source.url.startsWith("https://") && item.risk && item.application,
    ),
  );
  // 3 iniciales + 4 de la tanda 2026-10-20 con fuente en cartas de Buffett
  // (foso competitivo, owner earnings, capex mantenimiento/crecimiento, compounder).
  assert.equal(conceptsForInvestor("buffett").length, 7);
  assert.equal(conceptsForInvestor("munger").length, 0);
  assert.deepEqual(
    CONCEPTS.find(
      (item: { slug: string; investors: string[] }) => item.slug === "opciones",
    )?.investors,
    [],
  );
  // Textos del ejemplo en el diccionario español (solo la sección payoff).
  const diagram = read("app/(root)/inversores/conceptos/OptionPayoff.tsx") +
    JSON.stringify(JSON.parse(read("lib/i18n/messages/es/investors.json")).payoff);
  assert.match(diagram, /Ejemplo hipotético/);
  assert.match(diagram, /payoff-desc/);
  assert.match(diagram, /sin comisiones ni impuestos/);
});
test("all managers use source-labelled portfolios; no 13F filter or top-ten truncation", () => {
  assert.ok(
    !read("app/(root)/inversores/page.tsx").includes(".filter("), // carteras fusionada en el hub (decision de Nico, 2026-10-20)
  );
  const detail = read("app/(root)/inversores/[slug]/page.tsx");
  assert.match(detail, /getInvestorPortfolio\(slug\)/);
  assert.match(detail, /<InvestorLetters/);
  // conceptos siguen transversales, fuera de la ficha.
  assert.match(detail, /<InvestorViewSelector/);
  assert.ok(!detail.includes("holdings.slice(0, 10)"));
  const portfolio = read("app/(root)/inversores/_components/Portfolio.tsx");
  for (const text of [
    "Number.isFinite",
    "SIN_DATOS",
    "source_url",
    "INFERIDO",
    "Pagination",
    "portfolio.limitations",
  ])
    assert.ok(portfolio.includes(text), text);
});
test("hub exposes each section with selected state and real page navigation", () => {
  const nav = read("app/(root)/inversores/_components/HubNav.tsx");
  // Barra final del hub fusionado (decisión de Nico, WhatsApp 2026-10-20
  // 00:59 y 01:15): 4 destinos. Carteras queda dentro de Inversores (PR 1);
  // Cartas, Vídeos y Conceptos cuelgan de Aprender (PR 3 los fusiona).
  for (const name of [
    "Inversores",
    "13F",
    "Insiders",
    "Aprender",
    "aria-current",
  ])
    assert.ok(nav.includes(name));
  const video = read("app/(root)/inversores/videos/page.tsx");
  assert.match(video, /Pagination/);
  assert.match(video, /some\(\(item\) => item.slug === inversor\)/);
  assert.ok(!video.includes("Promise.all"));
});
