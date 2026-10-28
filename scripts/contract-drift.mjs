#!/usr/bin/env node
/**
 * contract-drift: deriva de contrato frontend <-> data-engine.
 *
 * Compara las llamadas del frontend (researchRequest/requestJson/getJson/
 * postJson/postForm/fetchJson en lib/, components/, hooks/, app/) con el
 * OpenAPI del data-engine (data-engine/openapi.json por defecto):
 *   - endpoint inexistente o metodo no soportado
 *   - campos del tipo TS ausentes en el schema de respuesta
 *   - campos nullable en backend tratados como obligatorios en TS
 *   - enums: literales TS fuera del enum backend y valores backend sin cubrir
 *   - query params enviados que el endpoint no declara (FastAPI los ignora
 *     en silencio: filtros que no filtran) y obligatorios no enviados
 *   - cuerpos JSON/FormData con campos ajenos o sin campos obligatorios
 *   - Decimal en el wire (anyOf number+string: FastAPI serializa Decimal
 *     como string) tipado como number en TS
 *
 * Uso:  node scripts/contract-drift.mjs [--openapi RUTA] [--json] [--no-allowlist]
 * Salida 1 si hay hallazgos fuera de scripts/contract-drift.allowlist.json.
 * Requiere `npm ci` (usa la dependencia de desarrollo `typescript`).
 */
import ts from 'typescript';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function loadArgs(argv) {
  const args = { openapi: path.join(ROOT, 'data-engine', 'openapi.json'), json: false, allowlist: true };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i] === '--openapi') args.openapi = path.resolve(argv[++i]);
    else if (argv[i] === '--json') args.json = true;
    else if (argv[i] === '--no-allowlist') args.allowlist = false;
  }
  return args;
}

/**
 * @param {{ root?: string, openapiPath?: string }} [options]
 */
export function scanContract({ root = ROOT, openapiPath } = {}) {
  const spec = JSON.parse(fs.readFileSync(openapiPath ?? path.join(root, 'data-engine', 'openapi.json'), 'utf8'));

  function deref(s, seen = new Set()) {
    while (s && s.$ref) {
      const ref = s.$ref;
      if (seen.has(ref)) return {};
      seen.add(ref);
      s = spec.components?.schemas?.[ref.replace('#/components/schemas/', '')] ?? {};
    }
    if (s && s.allOf) {
      const merged = { type: 'object', properties: {}, required: [] };
      for (const part of s.allOf) {
        const p = deref(part, new Set(seen));
        Object.assign(merged.properties, p.properties ?? {});
        merged.required.push(...(p.required ?? []));
      }
      return merged;
    }
    if (s && (s.anyOf || s.oneOf)) {
      const variants = (s.anyOf ?? s.oneOf).map((v) => deref(v, new Set(seen)));
      const nonNull = variants.filter((v) => v.type !== 'null');
      const nullable = variants.length !== nonNull.length;
      if (nonNull.length === 1) return { ...nonNull[0], nullable: nullable || undefined };
      return { anyOfVariants: nonNull, nullable: nullable || undefined };
    }
    return s ?? {};
  }

  const specPaths = Object.keys(spec.paths ?? {});
  const specPathRegexes = specPaths.map((p) => ({
    p,
    re: new RegExp('^' + p.replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\{[^}]+\}/g, '[^/]+') + '$'),
  }));

  function matchSpecPath(pattern) {
    let pathOnly = pattern.split('?')[0];
    if (!pathOnly.startsWith('/')) return [];
    while (pathOnly.endsWith('\0') && pathOnly.length > 1 && pathOnly[pathOnly.length - 2] !== '/') pathOnly = pathOnly.slice(0, -1);
    const re = new RegExp('^' + pathOnly.split('\0').map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^/]+') + '$');
    const hits = specPathRegexes.filter(({ p }) => re.test(p));
    if (hits.length <= 1) return hits.map((h) => h.p);
    const patSegs = pathOnly.split('/');
    const scored = hits.map(({ p }) => {
      const segs = p.split('/');
      let score = 0;
      for (let i = 0; i < Math.min(segs.length, patSegs.length); i++) {
        if (segs[i] === patSegs[i]) score += 2;
        else if (/^\{[^}]+\}$/.test(segs[i])) score += 1;
      }
      return { p, score };
    });
    scored.sort((a, b) => b.score - a.score);
    return scored.filter((s) => s.score === scored[0].score).map((s) => s.p);
  }

  const successSchema = (op) => {
    const r = op?.responses ?? {};
    for (const code of ['200', '201', '202', '204', '2XX', 'default']) {
      const sch = r[code]?.content?.['application/json']?.schema;
      if (sch) return deref(sch);
    }
    return null;
  };
  const requestSchema = (op) => {
    const c = op?.requestBody?.content ?? {};
    const sch = c['application/json']?.schema ?? c['multipart/form-data']?.schema;
    return sch ? deref(sch) : null;
  };

  function walk(dir, out = []) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name.startsWith('.')) continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) walk(full, out);
      else if (/\.(ts|tsx)$/.test(e.name) && !/\.(d|test|spec)\.ts$/.test(e.name)) out.push(full);
    }
    return out;
  }
  const files = [];
  for (const d of ['lib', 'components', 'hooks', 'app']) {
    const full = path.join(root, d);
    if (fs.existsSync(full)) walk(full, files);
  }

  const program = ts.createProgram(files, {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler, jsx: ts.JsxEmit.ReactJSX,
    strict: true, baseUrl: root, paths: { '@/*': ['*'] },
    esModuleInterop: true, skipLibCheck: true, noEmit: true, types: [],
  });
  const checker = program.getTypeChecker();

  const HELPERS = {
    researchRequest: { fixedMethod: null, initIndex: 1 },
    requestJson: { fixedMethod: null, initIndex: 1 },
    fetchJson: { fixedMethod: null, initIndex: 1 },
    getJson: { fixedMethod: 'get', initIndex: null, bodyIndex: null },
    postJson: { fixedMethod: 'post', initIndex: null, bodyIndex: 2 },
    postForm: { fixedMethod: 'post', initIndex: null, bodyIndex: 2, form: true },
  };
  const findings = [];
  const stats = { calls: 0, typed: 0, untyped: 0, unmatched: [] };

  function queryNamesFromArg(arg) {
    const names = new Set();
    if (!arg) return { names, complete: true };
    let hasHoleInQuery = false;
    const scanLit = (text, inQ) => {
      const qi = text.indexOf('?');
      const rest = inQ ? text : qi >= 0 ? text.slice(qi) : null;
      if (rest) for (const m of rest.matchAll(/[?&]([a-zA-Z_][a-zA-Z0-9_-]*)=/g)) names.add(m[1]);
      return inQ || qi >= 0;
    };
    if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) { scanLit(arg.text, false); return { names, complete: true }; }
    if (ts.isTemplateExpression(arg)) {
      let inQ = scanLit(arg.head.text, false);
      for (const span of arg.templateSpans) {
        if (inQ && !ts.isStringLiteral(span.expression)) hasHoleInQuery = true;
        inQ = scanLit(span.literal.text, inQ);
      }
      return { names, complete: !hasHoleInQuery };
    }
    return { names, complete: false };
  }

  function pathPatternFromArg(arg) {
    if (!arg) return null;
    if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) return arg.text;
    if (ts.isTemplateExpression(arg)) {
      let pat = arg.head.text;
      for (const span of arg.templateSpans) {
        const e = span.expression;
        const hole = ts.isStringLiteral(e) ? e.text
          : ts.isCallExpression(e) && e.arguments.length && ts.isStringLiteral(e.arguments[0]) ? e.arguments[0].text : '\0';
        pat += hole + span.literal.text;
      }
      return pat;
    }
    return null;
  }

  const methodFromInit = (init) => {
    if (init && ts.isObjectLiteralExpression(init)) {
      for (const prop of init.properties) {
        if (ts.isPropertyAssignment(prop) && prop.name.getText() === 'method' && ts.isStringLiteral(prop.initializer)) {
          return prop.initializer.text.toLowerCase();
        }
      }
    }
    return 'get';
  };

  const enclosingFunction = (node) => {
    let n = node.parent;
    while (n && !(ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n) || ts.isArrowFunction(n) || ts.isMethodDeclaration(n))) n = n.parent;
    return n;
  };

  function constructedNames(node, ctor) {
    const fn = enclosingFunction(node);
    if (!fn || !fn.body) return new Set();
    const vars = new Set();
    const collect = (n) => {
      if (ts.isVariableDeclaration(n) && n.initializer && ts.isNewExpression(n.initializer)
          && n.initializer.expression.getText() === ctor && ts.isIdentifier(n.name)) vars.add(n.name.text);
      ts.forEachChild(n, collect);
    };
    collect(fn.body);
    const names = new Set();
    const visit2 = (n) => {
      if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression)
          && ts.isIdentifier(n.expression.expression) && vars.has(n.expression.expression.text)) {
        const m = n.expression.name.getText();
        if ((m === 'set' || m === 'append') && n.arguments.length && ts.isStringLiteral(n.arguments[0])) names.add(n.arguments[0].text);
      }
      ts.forEachChild(n, visit2);
    };
    visit2(fn.body);
    return names;
  }

  function bodyTypeFromInit(init) {
    if (!init || !ts.isObjectLiteralExpression(init)) return null;
    for (const prop of init.properties) {
      if (ts.isPropertyAssignment(prop) && prop.name.getText() === 'body') {
        const v = prop.initializer;
        if (ts.isCallExpression(v) && (v.expression.getText() === 'jsonBody' || v.expression.getText() === 'JSON.stringify') && v.arguments.length) {
          return checker.getTypeAtLocation(v.arguments[0]);
        }
        if (ts.isObjectLiteralExpression(v)) return checker.getTypeAtLocation(v);
      }
    }
    return null;
  }

  function tsScalarKinds(t) {
    const kinds = new Set();
    for (const p of t.isUnion() ? t.types : [t]) {
      if (p.flags & (ts.TypeFlags.Number | ts.TypeFlags.NumberLiteral)) kinds.add('number');
      else if (p.flags & (ts.TypeFlags.String | ts.TypeFlags.StringLiteral)) kinds.add('string');
      else if (p.flags & (ts.TypeFlags.Boolean | ts.TypeFlags.BooleanLiteral)) kinds.add('boolean');
      else if (p.flags & (ts.TypeFlags.Undefined | ts.TypeFlags.Null | ts.TypeFlags.Void)) continue;
      else kinds.add('other');
    }
    return kinds;
  }
  const scalarKindOfSchema = (s) => (s.type === 'integer' || s.type === 'number' ? 'number' : s.type === 'string' ? 'string' : s.type === 'boolean' ? 'boolean' : null);

  function literalUnionStrings(t) {
    if (!t.isUnion()) return null;
    const vals = [];
    for (const part of t.types) {
      if (part.isStringLiteral()) vals.push(part.value);
      else if (part.flags & (ts.TypeFlags.Undefined | ts.TypeFlags.Null)) continue;
      else return null;
    }
    return vals;
  }
  function schemaEnum(s) {
    if (s.enum) return s.enum.filter((v) => v !== null);
    if (s.anyOfVariants) {
      const all = [];
      for (const v of s.anyOfVariants) {
        if (v.const !== undefined) all.push(v.const);
        else if (v.enum) all.push(...v.enum.filter((x) => x !== null));
        else return null;
      }
      return all;
    }
    if (s.const !== undefined) return [s.const];
    return null;
  }

  function compareType(tsType, schema, ctx, depth, node) {
    if (!schema) return;
    schema = deref(schema);
    if (schema.type === 'array' && schema.items) {
      const idx = tsType.getNumberIndexType() ?? checker.getIndexTypeOfType(tsType, ts.IndexKind.Number);
      if (idx) return compareType(idx, deref(schema.items), ctx, depth, node);
      return;
    }
    if (schema.anyOfVariants) {
      const obj = schema.anyOfVariants.find((v) => (v.properties && Object.keys(v.properties).length) || v.type === 'object');
      if (obj) schema = obj; else return;
    }
    const sProps = schema.properties ?? {};
    const allowsExtra = schema.additionalProperties === true || (schema.additionalProperties && typeof schema.additionalProperties === 'object');
    for (const sym of tsType.getProperties()) {
      const name = sym.getName();
      if (name.startsWith('__')) continue;
      const optional = (sym.flags & ts.SymbolFlags.Optional) !== 0;
      const decls = sym.getDeclarations() ?? [];
      const propType = decls.length ? checker.getTypeOfSymbolAtLocation(sym, decls[0]) : checker.getTypeOfSymbolAtLocation(sym, node);
      const nonNullProp = checker.getNonNullableType(propType);
      const propNullable = nonNullProp !== propType;
      if (!(name in sProps)) {
        if (!allowsExtra) findings.push({ kind: 'FIELD_NOT_IN_SCHEMA', ...ctx, field: name, tsOptional: optional });
        continue;
      }
      const sub = deref(sProps[name]);
      if (!optional && !propNullable && sub.nullable) {
        findings.push({ kind: 'BACKEND_NULLABLE_TS_REQUIRED', ...ctx, field: name });
      }
      if (sub.anyOfVariants) {
        const vk = new Set(sub.anyOfVariants.map((v) => scalarKindOfSchema(v)).filter(Boolean));
        if (vk.size === 2 && vk.has('number') && vk.has('string')) {
          const tk = tsScalarKinds(nonNullProp);
          if (tk.has('number') && !tk.has('string') && !tk.has('other')) findings.push({ kind: 'DECIMAL_WIRE_STRING_TS_NUMBER', ...ctx, field: name });
        }
      } else {
        const sk = scalarKindOfSchema(sub);
        if (sk) {
          const tk = tsScalarKinds(nonNullProp);
          if (tk.size === 1 && !tk.has(sk) && !tk.has('other')) findings.push({ kind: 'SCALAR_TYPE_MISMATCH', ...ctx, field: name, backend: sk, frontend: [...tk][0] });
        } else if (sub.type === 'array') {
          const tk = tsScalarKinds(nonNullProp);
          if (!nonNullProp.getNumberIndexType() && (tk.has('number') || tk.has('string') || tk.has('boolean'))) findings.push({ kind: 'SHAPE_MISMATCH', ...ctx, field: name, backend: 'array' });
        } else if ((sub.type === 'object' || sub.properties) && sub.properties) {
          const tk = tsScalarKinds(nonNullProp);
          if (tk.has('number') || tk.has('string') || tk.has('boolean')) findings.push({ kind: 'SHAPE_MISMATCH', ...ctx, field: name, backend: 'object' });
        }
      }
      const tsEnum = literalUnionStrings(nonNullProp);
      const beEnum = schemaEnum(sub);
      if (tsEnum && beEnum) {
        const extra = tsEnum.filter((v) => !beEnum.includes(v));
        const missing = beEnum.filter((v) => !tsEnum.includes(v));
        if (extra.length) findings.push({ kind: 'ENUM_TS_VALUE_NOT_IN_BACKEND', ...ctx, field: name, values: extra });
        if (missing.length) findings.push({ kind: 'ENUM_BACKEND_VALUE_UNHANDLED', ...ctx, field: name, values: missing });
      }
      if (depth < 2 && (sub.properties || (sub.type === 'array' && deref(sub.items ?? {}).properties))) {
        const eff = sub.type === 'array' ? nonNullProp.getNumberIndexType() : nonNullProp;
        if (eff && eff.getProperties().length && !(eff.flags & (ts.TypeFlags.String | ts.TypeFlags.Number | ts.TypeFlags.Boolean))) {
          compareType(eff, sub.type === 'array' ? deref(sub.items) : sub, { ...ctx, fieldPrefix: (ctx.fieldPrefix ?? '') + name + '.' }, depth + 1, node);
        }
      }
    }
  }

  for (const file of files) {
    const sf = program.getSourceFile(file);
    if (!sf) continue;
    const rel = path.relative(root, file);
    const visit = (node) => {
      if (ts.isCallExpression(node)) {
        const base = node.expression.getText(sf).split('.').pop();
        const helper = HELPERS[base];
        if (helper) {
          stats.calls++;
          const pat = pathPatternFromArg(node.arguments[0]);
          if (pat) {
            const matches = matchSpecPath(pat);
            const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
            const lineNo = line + 1;
            if (!matches.length) {
              if (pat.startsWith('/')) {
                const method = helper.fixedMethod ?? methodFromInit(helper.initIndex != null ? node.arguments[helper.initIndex] : undefined);
                const item = { file: rel, line: lineNo, pattern: pat.replace(/\0/g, '${...}') };
                stats.unmatched.push({ ...item, reason: pat.includes('\0') ? 'dynamic-unresolved' : 'static-missing' });
                if (!pat.includes('\0')) findings.push({ kind: 'ENDPOINT_NOT_IN_SPEC', ...item, endpoint: `${method.toUpperCase()} ${pat.split('?')[0]}` });
              }
            } else {
              const specPath = matches[0];
              const method = helper.fixedMethod ?? methodFromInit(helper.initIndex != null ? node.arguments[helper.initIndex] : undefined);
              const op = spec.paths[specPath]?.[method];
              const ctx = { file: rel, line: lineNo, endpoint: `${method.toUpperCase()} ${specPath}` };
              if (!op) {
                findings.push({ kind: 'METHOD_NOT_IN_SPEC', ...ctx, available: Object.keys(spec.paths[specPath] ?? {}) });
              } else {
                const typeNode = node.typeArguments?.[0];
                if (typeNode) {
                  stats.typed++;
                  const t = checker.getTypeFromTypeNode(typeNode);
                  if (!(t.flags & ts.TypeFlags.Any) && !(t.flags & ts.TypeFlags.Unknown)) {
                    const rs = successSchema(op);
                    if (rs) {
                      const parts = t.isUnion() ? t.types.filter((x) => !(x.flags & (ts.TypeFlags.Null | ts.TypeFlags.Undefined))) : [t];
                      for (const rt of parts) {
                        const rk = tsScalarKinds(rt);
                        if (rk.has('number') || rk.has('string') || rk.has('boolean')) continue;
                        if (rs.type === 'array' && !rt.getNumberIndexType()) continue;
                        if (rs.type !== 'array' && rt.getNumberIndexType()) {
                          findings.push({ kind: 'SHAPE_MISMATCH', ...ctx, field: '(root)', backend: rs.type ?? 'object', frontend: 'array' });
                          continue;
                        }
                        compareType(rt, rs, ctx, 0, node);
                      }
                    }
                  }
                } else stats.untyped++;
                const q = queryNamesFromArg(node.arguments[0]);
                const fnNode = enclosingFunction(node);
                let holeCalls = 0;
                if (fnNode && fnNode.body) {
                  const countHoles = (n) => {
                    if (ts.isCallExpression(n) && HELPERS[n.expression.getText(sf).split('.').pop()]) {
                      if (!queryNamesFromArg(n.arguments[0]).complete) holeCalls++;
                    }
                    ts.forEachChild(n, countHoles);
                  };
                  countHoles(fnNode.body);
                }
                if (!q.complete && holeCalls === 1) for (const n of constructedNames(node, 'URLSearchParams')) q.names.add(n);
                const specQ = new Set((op.parameters ?? []).filter((p) => p.in === 'query').map((p) => p.name));
                const specQRequired = new Set((op.parameters ?? []).filter((p) => p.in === 'query' && p.required).map((p) => p.name));
                for (const n of q.names) {
                  if (!specQ.has(n)) findings.push({ kind: 'QUERY_PARAM_NOT_IN_SPEC', ...ctx, field: n });
                }
                if (q.complete) {
                  for (const rq of specQRequired) {
                    if (!q.names.has(rq)) findings.push({ kind: 'QUERY_PARAM_REQUIRED_NOT_SENT', ...ctx, field: rq });
                  }
                }
                let bt = bodyTypeFromInit(node.arguments[1]);
                if (helper.bodyIndex != null && node.arguments[helper.bodyIndex]) {
                  const barg = node.arguments[helper.bodyIndex];
                  if (helper.form) {
                    const fdNames = constructedNames(node, 'FormData');
                    const bs0 = requestSchema(op);
                    if (bs0 && fdNames.size) {
                      const bProps = bs0.properties ?? {};
                      const bReq = new Set(bs0.required ?? []);
                      for (const nm of fdNames) if (!(nm in bProps)) findings.push({ kind: 'FORMDATA_FIELD_NOT_IN_SCHEMA', ...ctx, field: nm });
                      for (const rq of bReq) if (!fdNames.has(rq)) findings.push({ kind: 'FORMDATA_REQUIRED_FIELD_MISSING', ...ctx, field: rq });
                    }
                  } else if (ts.isObjectLiteralExpression(barg)) {
                    bt = checker.getTypeAtLocation(barg);
                  }
                }
                const bs = requestSchema(op);
                if (bt && bs) {
                  const bProps = bs.properties ?? {};
                  const bReq = new Set(bs.required ?? []);
                  const bodyCtx = { ...ctx, fieldPrefix: 'body.' };
                  for (const sym of bt.getProperties()) {
                    const nm = sym.getName();
                    if (!(nm in bProps)) findings.push({ kind: 'BODY_FIELD_NOT_IN_SCHEMA', ...bodyCtx, field: nm });
                  }
                  for (const rq of bReq) {
                    if (!bt.getProperty(rq)) findings.push({ kind: 'BODY_REQUIRED_FIELD_MISSING', ...bodyCtx, field: rq });
                  }
                }
              }
            }
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  return { stats: { ...stats, unmatchedCount: stats.unmatched.length }, findings };
}

export function loadAllowlist(root = ROOT) {
  const p = path.join(root, 'scripts', 'contract-drift.allowlist.json');
  if (!fs.existsSync(p)) return [];
  return JSON.parse(fs.readFileSync(p, 'utf8')).entries ?? [];
}

export function applyAllowlist(findings, entries) {
  return findings.filter((f) => !entries.some((e) =>
    e.kind === f.kind && e.endpoint === f.endpoint && e.field === f.field
    && (!e.values || JSON.stringify(e.values) === JSON.stringify(f.values))));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = loadArgs(process.argv);
  const { stats, findings } = scanContract({ openapiPath: args.openapi });
  const open = args.allowlist ? applyAllowlist(findings, loadAllowlist()) : findings;
  const summary = {
    calls: stats.calls, typed: stats.typed, untyped: stats.untyped,
    unmatchedPatterns: stats.unmatchedCount, findings: findings.length,
    allowlisted: findings.length - open.length, open: open.length,
  };
  if (args.json) console.log(JSON.stringify({ summary, findings, open, unmatched: stats.unmatched }, null, 1));
  else {
    console.log('contract-drift:', JSON.stringify(summary));
    for (const f of open) console.log(`  ${f.kind} ${f.file}:${f.line} ${f.endpoint} ${f.field ?? ''} ${f.values ? JSON.stringify(f.values) : ''}`.trim());
    if (stats.unmatchedCount) console.log('  (patrones no resueltos, limitacion conocida: query en hueco de template)');
  }
  process.exit(open.length ? 1 : 0);
}
