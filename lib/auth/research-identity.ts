import { createHash, createHmac, randomBytes } from 'node:crypto';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { AppError } from '@/lib/types/errors';

/** Raw request-body bytes that will be sent verbatim. */
export type ResearchBody = string | Uint8Array | ArrayBuffer;

/** The exact request a signature is bound to (anti-replay / anti-tampering). */
export interface ResearchRequestTarget {
  method: string;
  /** Full URL or path; only the pathname (no query string) is signed. */
  path: string;
  /** The exact bytes sent verbatim as the request body (optional). */
  body?: ResearchBody | null;
}

/** Normalized body: bytes that can be handed to fetch as-is. */
export interface NormalizedResearchBody {
  body?: string | ArrayBuffer;
  contentType?: string;
}

/**
 * Pathname of a URL or path, without the query string, in the DECODED form the
 * data engine sees (`request.url.path` is percent-decoded). Signing the encoded
 * path made tickers such as `^GSPC` (`%5EGSPC`) fail with 401. If decoding is
 * not possible or yields non printable-ASCII (header-unsafe), the encoded path
 * is kept.
 */
export function researchRequestPath(target: string): string {
  let pathname: string;
  try {
    pathname = new URL(target).pathname;
  } catch {
    pathname = target.split('?')[0] ?? target;
  }
  try {
    const decoded = decodeURIComponent(pathname);
    return /^[\x20-\x7e]*$/.test(decoded) ? decoded : pathname;
  } catch {
    return pathname;
  }
}

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.buffer.slice(
    bytes.byteOffset,
    bytes.byteOffset + bytes.byteLength,
  ) as ArrayBuffer;
}

function bodyBytes(body: ResearchBody | null | undefined): Buffer {
  if (body == null) return Buffer.alloc(0);
  if (typeof body === 'string') return Buffer.from(body, 'utf8');
  if (body instanceof ArrayBuffer) return Buffer.from(body);
  return Buffer.from(body);
}

/**
 * Normalize any BodyInit into bytes that will be sent verbatim, so the signed
 * body hash matches what the data engine receives (FormData/URLSearchParams
 * are serialized once here — fetch would otherwise pick a fresh multipart
 * boundary per attempt and the hash would never match).
 */
export async function normalizeResearchBody(
  body: BodyInit | null | undefined,
): Promise<NormalizedResearchBody> {
  if (body == null) return {};
  if (typeof body === 'string') return { body };
  if (body instanceof Uint8Array) return { body: toArrayBuffer(body) };
  if (body instanceof ArrayBuffer) return { body };
  const serialized = new Response(body);
  const bytes = await serialized.arrayBuffer();
  const contentType = serialized.headers.get('content-type') ?? undefined;
  return contentType ? { body: bytes, contentType } : { body: bytes };
}

/**
 * Build the short-lived signed identity accepted by the private data engine.
 *
 * The HMAC covers tenant, user, timestamp, a single-use nonce, the HTTP
 * method, the request path and the SHA-256 of the raw body: a captured
 * signature cannot be replayed (nonce), nor moved to another endpoint,
 * method or a tampered body.
 */
export async function researchIdentityHeaders(
  target: ResearchRequestTarget,
): Promise<Record<string, string>> {
  const secret = process.env.RESEARCH_AUTH_SECRET;
  if (!secret || secret.length < 32) {
    throw new AppError(
      'Research authentication is not configured',
      'RESEARCH_AUTH_NOT_CONFIGURED',
      503,
    );
  }

  const user = await requireAuthenticatedUser();
  const tenantId = user.id;
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = randomBytes(16).toString('hex');
  const method = target.method.toUpperCase();
  const path = researchRequestPath(target.path);
  const bodyHash = createHash('sha256').update(bodyBytes(target.body)).digest('hex');
  const signature = createHmac('sha256', secret)
    .update(`${tenantId}:${user.id}:${timestamp}:${nonce}:${method}:${path}:${bodyHash}`)
    .digest('hex');

  return {
    'X-CavaAI-User': user.id,
    'X-CavaAI-Tenant': tenantId,
    'X-CavaAI-Timestamp': timestamp,
    'X-CavaAI-Nonce': nonce,
    'X-CavaAI-Method': method,
    'X-CavaAI-Path': path,
    'X-CavaAI-Body-Hash': bodyHash,
    'X-CavaAI-Signature': signature,
  };
}
