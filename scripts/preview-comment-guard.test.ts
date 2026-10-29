// Guard del workflow preview.yml: ejecuta el script real del paso
// "Marca el comentario como obsoleto" contra un github-script simulado.
// Cubre: listado vacio, con comentario, update 404, list 404, update 403/500.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const MARKER = "<!-- cavaai-vercel-preview -->";
const yml = readFileSync(new URL("../.github/workflows/preview.yml", import.meta.url), "utf8").split("\n");

function extractScript(stepName: string): string {
  const start = yml.findIndex((l) => l.includes(`name: ${stepName}`));
  assert.ok(start >= 0, `paso no encontrado: ${stepName}`);
  const sc = yml.findIndex((l, i) => i > start && /^\s*script:\s*\|/.test(l));
  assert.ok(sc > start, "script no encontrado");
  const base = yml[sc].search(/\S/);
  const out: string[] = [];
  for (let i = sc + 1; i < yml.length; i++) {
    const l = yml[i];
    if (l.trim() !== "" && l.search(/\S/) <= base) break;
    out.push(l.slice(base + 2));
  }
  return out.join("\n");
}

const CLOSED = extractScript("Marca el comentario como obsoleto");
const PUBLISH = extractScript("Publica o actualiza el comentario del preview");
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

type Err = { status: number };
function run(code: string, opts: { list?: unknown[]; listError?: Err; updateError?: Err }) {
  const updates: number[] = [];
  const infos: string[] = [];
  const github = {
    paginate: async () => {
      if (opts.listError) throw Object.assign(new Error("list"), opts.listError);
      return opts.list ?? [];
    },
    rest: {
      issues: {
        listComments: () => {},
        createComment: async () => ({}),
        updateComment: async (a: { comment_id: number }) => {
          if (opts.updateError) throw Object.assign(new Error("update"), opts.updateError);
          updates.push(a.comment_id);
          return {};
        },
      },
    },
  };
  const context = {
    issue: { owner: "o", repo: "r", number: 1 },
    repo: { owner: "o", repo: "r" },
    serverUrl: "https://github.com",
    runId: 1,
  };
  const core = { info: (m: string) => infos.push(m), warning: () => {}, setFailed: () => {} };
  const proc = { env: { PREVIEW_MARKER: MARKER, PR_BRANCH: "x", PREVIEW_URL: "https://a.vercel.app", PREVIEW_SHA: "abc1234" } };
  const fn = new AsyncFunction("github", "context", "core", "process", code);
  return fn(github, context, core, proc).then(() => ({ updates, infos }));
}

test("listado vacio: no falla y no actualiza nada", async () => {
  const r = await run(CLOSED, { list: [] });
  assert.deepEqual(r.updates, []);
});
test("listado con comentario: se marca como obsoleto", async () => {
  const r = await run(CLOSED, { list: [{ id: 7, body: `${MARKER}\nhola` }, { id: 8, body: "otro" }] });
  assert.deepEqual(r.updates, [7]);
});
test("update 404: se tolera", async () => {
  const r = await run(CLOSED, { list: [{ id: 7, body: MARKER }], updateError: { status: 404 } });
  assert.deepEqual(r.updates, []);
});
test("list 404: se tolera", async () => {
  await run(CLOSED, { listError: { status: 404 } });
});
for (const status of [403, 500]) {
  test(`update ${status}: debe fallar`, async () => {
    await assert.rejects(run(CLOSED, { list: [{ id: 7, body: MARKER }], updateError: { status } }));
  });
  test(`list ${status}: debe fallar`, async () => {
    await assert.rejects(run(CLOSED, { listError: { status } }));
  });
}
test("paso de publicar usa el array de paginate (sin {data})", async () => {
  await run(PUBLISH, { list: [] });
  await run(PUBLISH, { list: [{ id: 3, body: MARKER }] });
});

test("ningun camino del workflow activa el deploy de previews por CLI", () => {
  const text = yml.join("\n");
  // El gate nunca puede dejar deploy=true, haya o no secrets.
  assert.doesNotMatch(text, /deploy=true/);
  assert.match(text, /deploy=false/);
  // Sin deploy no hay comentario que publicar en el PR.
  assert.match(text, /Previews de rama\/PR desactivados: solo main despliega/);
  // vercel.json: ningun push ni merge despliega por Git; solo orden manual.
  const vercel = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  assert.equal(vercel.git.deploymentEnabled, false);
});
