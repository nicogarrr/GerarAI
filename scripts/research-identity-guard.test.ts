/**
 * Guard de identidad firmada research (auditoria): el HMAC va ligado a
 * tenant, usuario, timestamp, nonce unico, metodo, path y hash del body.
 *
 * Limite documentado: `researchIdentityHeaders` exige identidad autenticada;
 * aqui se sustituye SOLO el modulo de identidad por un stub fijo (misma
 * semantica que E2E_AUTH_BYPASS=1) mediante el loader co-ubicado. Todo el
 * codigo criptografico bajo test es el fuente real. El rechazo de timestamps
 * futuros (skew) lo aplica el servidor en data-engine/app/core/auth.py; aqui
 * se fija el contrato cliente: timestamp = floor(now), nunca futuro.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/research-identity-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { register } from 'node:module';

register('./research-identity-guard.loader.mjs', import.meta.url);

// @ts-expect-error TS5097: la extension .ts explicita la exige node --experimental-strip-types en runtime
const identity = await import('../lib/auth/research-identity.ts');
const { researchIdentityHeaders, researchRequestPath, normalizeResearchBody } = identity;

const USER = 'guard-test-user';
const SECRET = 'guard-test-secret-with-at-least-32-chars!!';
const FIXED_MS = 1780000000 * 1000;

function sha256Hex(body: string): string {
  return createHash('sha256').update(Buffer.from(body, 'utf8')).digest('hex');
}

function expectedSignature(parts: {
  timestamp: string;
  nonce: string;
  method: string;
  path: string;
  bodyHash: string;
}): string {
  const payload =
    `${USER}:${USER}:${parts.timestamp}:${parts.nonce}:` +
    `${parts.method}:${parts.path}:${parts.bodyHash}`;
  return createHmac('sha256', SECRET).update(payload).digest('hex');
}

function withFixedEnv(fn: () => Promise<void>): Promise<void> {
  const prevSecret = process.env.RESEARCH_AUTH_SECRET;
  const prevNow = Date.now;
  process.env.RESEARCH_AUTH_SECRET = SECRET;
  Date.now = () => FIXED_MS;
  return fn().finally(() => {
    if (prevSecret === undefined) delete process.env.RESEARCH_AUTH_SECRET;
    else process.env.RESEARCH_AUTH_SECRET = prevSecret;
    Date.now = prevNow;
  });
}

describe('researchIdentityHeaders: canonicalizacion HMAC', () => {
  it('firma el canon tenant:user:ts:nonce:METHOD:path:bodyHash', () =>
    withFixedEnv(async () => {
      const body = '{"statement":"Azure demand"}';
      const headers = await researchIdentityHeaders({
        method: 'post',
        path: '/api/memory/claims?marker=1',
        body,
      });
      // Metodo en mayusculas y path sin query: parte del canon firmado.
      assert.equal(headers['X-CavaAI-Method'], 'POST');
      assert.equal(headers['X-CavaAI-Path'], '/api/memory/claims');
      assert.equal(headers['X-CavaAI-Timestamp'], String(Math.floor(FIXED_MS / 1000)));
      assert.equal(headers['X-CavaAI-Body-Hash'], sha256Hex(body));
      assert.equal(
        headers['X-CavaAI-Signature'],
        expectedSignature({
          timestamp: headers['X-CavaAI-Timestamp'],
          nonce: headers['X-CavaAI-Nonce'],
          method: 'POST',
          path: '/api/memory/claims',
          bodyHash: sha256Hex(body),
        }),
      );
    }));

  it('emite un nonce unico por llamada (anti-replay)', () =>
    withFixedEnv(async () => {
      const target = { method: 'GET', path: '/api/memory/claims', body: '' };
      const first = await researchIdentityHeaders(target);
      const second = await researchIdentityHeaders(target);
      assert.notEqual(first['X-CavaAI-Nonce'], second['X-CavaAI-Nonce']);
      assert.notEqual(first['X-CavaAI-Signature'], second['X-CavaAI-Signature']);
    }));

  it('cualquier tamper del body invalida la firma', () =>
    withFixedEnv(async () => {
      const original = await researchIdentityHeaders({
        method: 'POST',
        path: '/api/memory/claims',
        body: '{"statement":"original"}',
      });
      const tamperedHash = sha256Hex('{"statement":"tampered"}');
      assert.notEqual(tamperedHash, original['X-CavaAI-Body-Hash']);
      // La firma original NO verifica contra el body manipulado.
      assert.notEqual(
        original['X-CavaAI-Signature'],
        expectedSignature({
          timestamp: original['X-CavaAI-Timestamp'],
          nonce: original['X-CavaAI-Nonce'],
          method: 'POST',
          path: '/api/memory/claims',
          bodyHash: tamperedHash,
        }),
      );
      // Cuerpo vacio vs cuerpo con contenido: firmas distintas.
      const empty = await researchIdentityHeaders({
        method: 'POST',
        path: '/api/memory/claims',
      });
      assert.notEqual(empty['X-CavaAI-Signature'], original['X-CavaAI-Signature']);
    }));

  it('mover la firma a otro metodo/path no verifica', () =>
    withFixedEnv(async () => {
      const headers = await researchIdentityHeaders({
        method: 'GET',
        path: '/api/memory/claims',
        body: '',
      });
      const moved = expectedSignature({
        timestamp: headers['X-CavaAI-Timestamp'],
        nonce: headers['X-CavaAI-Nonce'],
        method: 'POST',
        path: '/api/alerts',
        bodyHash: headers['X-CavaAI-Body-Hash'],
      });
      assert.notEqual(headers['X-CavaAI-Signature'], moved);
    }));

  it('timestamp = floor(now): el cliente nunca emite skew futuro', () =>
    withFixedEnv(async () => {
      const before = Math.floor(Date.now() / 1000);
      const headers = await researchIdentityHeaders({
        method: 'GET',
        path: '/api/memory/claims',
      });
      const emitted = Number(headers['X-CavaAI-Timestamp']);
      const after = Math.floor(Date.now() / 1000);
      assert.ok(emitted >= before && emitted <= after, 'timestamp fuera de ventana');
      assert.ok(emitted <= Math.floor(FIXED_MS / 1000), 'timestamp futuro prohibido');
    }));

  it('sin secreto configurado falla cerrado con 503', async () => {
    const prev = process.env.RESEARCH_AUTH_SECRET;
    delete process.env.RESEARCH_AUTH_SECRET;
    try {
      await assert.rejects(
        researchIdentityHeaders({ method: 'GET', path: '/x' }),
        (error: unknown) =>
          error instanceof Error &&
          (error as { code?: string }).code === 'RESEARCH_AUTH_NOT_CONFIGURED' &&
          (error as { statusCode?: number }).statusCode === 503,
      );
    } finally {
      if (prev !== undefined) process.env.RESEARCH_AUTH_SECRET = prev;
    }
  });
});

describe('researchRequestPath: canon puro del path', () => {
  it('extrae el pathname de una URL completa', () => {
    assert.equal(
      researchRequestPath('https://engine.local/api/memory/claims?x=1'),
      '/api/memory/claims',
    );
  });

  it('recorta el query de un path relativo', () => {
    assert.equal(researchRequestPath('/api/alerts?status=open'), '/api/alerts');
  });

  it('deja intacto un path sin query', () => {
    assert.equal(researchRequestPath('/api/thesis/MSFT/versions'), '/api/thesis/MSFT/versions');
    // El motor firma la ruta decodificada (request.url.path): ^ y = no se codifican al firmar.
    assert.equal(researchRequestPath('/api/companies/%5EGSPC/quote'), '/api/companies/^GSPC/quote');
    assert.equal(researchRequestPath('/api/companies/EURUSD%3DX/quote?x=1'), '/api/companies/EURUSD=X/quote');
    // No decodificable o no ASCII imprimible: se deja tal cual.
    assert.equal(researchRequestPath('/api/a/%E0%A4%A'), '/api/a/%E0%A4%A');
    assert.equal(researchRequestPath('/api/a/%C3%B1'), '/api/a/%C3%B1');
  });
});

describe('normalizeResearchBody: bytes identicos a los enviados', () => {
  it('string pasa tal cual, null no toca nada', async () => {
    assert.deepEqual(await normalizeResearchBody('hola'), { body: 'hola' });
    assert.deepEqual(await normalizeResearchBody(null), {});
    assert.deepEqual(await normalizeResearchBody(undefined), {});
  });

  it('Uint8Array se entrega como ArrayBuffer con los mismos bytes', async () => {
    const bytes = new Uint8Array([104, 111, 108, 97]);
    const normalized = await normalizeResearchBody(bytes);
    assert.ok(normalized.body instanceof ArrayBuffer);
    assert.deepEqual(new Uint8Array(normalized.body as ArrayBuffer), bytes);
  });
});

describe("contrato frontend-backend: headers contra el cliente OpenAPI generado", () => {
  // El oraculo es lib/research/openapi.generated.ts, generado DESDE el backend
  // (data-engine) y vigilado por el job CI "OpenAPI generated client drift":
  // si el backend cambiara los headers, el generado cambiaria y este test romperia.
  // No es un grep del propio frontend: el codigo bajo test produce los headers y
  // el artefacto generado por el backend decide si son los esperados.
  const EXPECTED = [
    "x-cavaai-user",
    "x-cavaai-tenant",
    "x-cavaai-timestamp",
    "x-cavaai-nonce",
    "x-cavaai-method",
    "x-cavaai-path",
    "x-cavaai-body-hash",
    "x-cavaai-signature",
  ];

  it("los 8 headers firmados existen como parametros documentados en el spec generado", async () => {
    const { readFile } = await import("node:fs/promises");
    const spec = await readFile(
      new URL("../lib/research/openapi.generated.ts", import.meta.url),
      "utf8",
    );
    for (const h of EXPECTED) {
      assert.ok(
        spec.includes(`"${h}"?: string | null;`),
        `el cliente OpenAPI generado ya no documenta ${h}: deriva frontend-backend`,
      );
    }
  });

  it("researchIdentityHeaders emite exactamente esos 8 y ninguno mas", () =>
    withFixedEnv(async () => {
      const headers = await researchIdentityHeaders({
        method: "get",
        path: "/api/thesis/MSFT",
        body: null,
      });
      const emitted = Object.keys(headers).map((k) => k.toLowerCase()).sort();
      assert.deepEqual(emitted, [...EXPECTED].sort());
    }));
});
