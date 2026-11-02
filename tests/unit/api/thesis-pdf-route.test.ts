import path from 'node:path';
import { readFileSync } from 'node:fs';

import { NextRequest } from 'next/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { buildMemoPdf, identity, user } = vi.hoisted(() => ({
    buildMemoPdf: vi.fn(),
    identity: vi.fn(),
    user: vi.fn(),
}));

vi.mock('@/lib/thesis/memo-pdf', () => ({ buildMemoPdf }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders: identity }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: user }));

const fixture = readFileSync(
    path.join(process.cwd(), 'data-engine/tests/release_thesis_matrix/fixtures/pdf_sparse_draft.md'),
    'utf8',
);

describe('GET /api/thesis/[ticker]/pdf', () => {
    beforeEach(() => {
        vi.resetModules();
        vi.clearAllMocks();
        vi.stubEnv('FMP_BACKEND_URL', 'https://backend.example');
        user.mockResolvedValue({ id: 'u1' });
        identity.mockResolvedValue({ 'x-research-user': 'u1' });
        buildMemoPdf.mockResolvedValue(Buffer.from([0x25, 0x50, 0x44, 0x46]));
    });

    it('pasa el memo canónico del borrador al PDF sin añadir valoración', async () => {
        expect(fixture).toContain('BORRADOR sin publicar');
        for (const forbidden of ['999', '888', '40 %', '$', 'Valoración y escenarios', 'Margen de seguridad']) {
            expect(fixture).not.toContain(forbidden);
        }
        const fetchMock = vi.fn().mockResolvedValue(new Response(fixture, { status: 200 }));
        vi.stubGlobal('fetch', fetchMock);
        const { GET } = await import('@/app/api/thesis/[ticker]/pdf/route');

        const response = await GET(
            new NextRequest('http://localhost/api/thesis/pdft/pdf?draft=1'),
            { params: Promise.resolve({ ticker: 'pdft' }) },
        );

        expect(response.status).toBe(200);
        expect(fetchMock).toHaveBeenCalledWith(
            'https://backend.example/api/thesis/PDFT/memo.md?draft=1',
            { headers: { 'x-research-user': 'u1' }, cache: 'no-store' },
        );
        expect(buildMemoPdf).toHaveBeenCalledTimes(1);
        expect(buildMemoPdf).toHaveBeenCalledWith(fixture);
        expect(Buffer.from(await response.arrayBuffer()).toString('latin1')).toBe('%PDF');
        expect(response.headers.get('Content-Type')).toBe('application/pdf');
        expect(response.headers.get('Content-Disposition')).toBe('attachment; filename="tesis-pdft-v1-borrador.pdf"');
        expect(response.headers.get('Cache-Control')).toBe('no-store');
    });

    it('reads the version of an English memo for the file name', async () => {
        const english = '# Thesis memo — PDFT (Pdft)\n\nVersion 3 · status published · rating buy\n';
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(english, { status: 200 })));
        const { GET } = await import('@/app/api/thesis/[ticker]/pdf/route');

        const response = await GET(
            new NextRequest('http://localhost/api/thesis/pdft/pdf'),
            { params: Promise.resolve({ ticker: 'pdft' }) },
        );

        expect(response.status).toBe(200);
        expect(buildMemoPdf).toHaveBeenCalledWith(english);
        expect(response.headers.get('Content-Disposition')).toBe('attachment; filename="thesis-pdft-v3.pdf"');
    });

    it('names an English draft or archived memo «thesis-…-draft.pdf»', async () => {
        const english = '# Thesis memo — PDFT (Pdft)\n\nVersion 2 · status draft · generated Oct 20, 2026, 14:03 UTC\n';
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(english, { status: 200 })));
        const { GET } = await import('@/app/api/thesis/[ticker]/pdf/route');

        const draft = await GET(
            new NextRequest('http://localhost/api/thesis/pdft/pdf?draft=1'),
            { params: Promise.resolve({ ticker: 'pdft' }) },
        );
        expect(draft.headers.get('Content-Disposition')).toBe('attachment; filename="thesis-pdft-v2-draft.pdf"');

        // Memo archivado en inglés: sin línea de versión, prefijo inglés igualmente.
        const archived = '# Thesis memo - PDFT\n\nArchived thesis v4 (2026-09-01): The model is not publishable.\n';
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(archived, { status: 200 })));
        const response = await GET(
            new NextRequest('http://localhost/api/thesis/pdft/pdf'),
            { params: Promise.resolve({ ticker: 'pdft' }) },
        );
        expect(response.headers.get('Content-Disposition')).toBe('attachment; filename="thesis-pdft.pdf"');
    });
});
