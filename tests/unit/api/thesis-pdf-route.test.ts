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
});
