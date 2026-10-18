import { withAuthErrors } from '@/lib/auth/route-auth';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

async function getHandler(request: Request, { params }: { params: Promise<{ ticker: string }> }) {
    await requireAuthenticatedUser();
    const { ticker } = await params;
    if (!/^[A-Za-z0-9.^=-]{1,32}$/.test(ticker)) return Response.json({ status: 'unavailable' }, { status: 400 });
    const since = new URL(request.url).searchParams.get('since') ?? '';
    // Solo una fecha ISO: nada de texto libre hacia el backend.
    if (!/^\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:\d{2})$/.test(since) || Number.isNaN(Date.parse(since))) {
        return Response.json({ status: 'unavailable' }, { status: 400 });
    }
    try {
        const data = await researchRequest<unknown>(
            `/api/companies/${encodeURIComponent(ticker)}/changes-since?since=${encodeURIComponent(since)}`,
        );
        return Response.json(data, { headers: { 'Cache-Control': 'no-store' } });
    } catch {
        return Response.json({ status: 'unavailable' }, { status: 502, headers: { 'Cache-Control': 'no-store' } });
    }
}

export const GET = withAuthErrors(getHandler);
