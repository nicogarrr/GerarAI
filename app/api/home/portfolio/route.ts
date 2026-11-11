import { withAuthErrors } from '@/lib/auth/route-auth';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getPortfolioSummary, type PortfolioSummary } from '@/lib/actions/portfolio.actions';
import { sectionResponse } from '@/lib/home/section-response';

/** Sección Cartera del inicio: responde en cuanto el resumen está (la más rápida). */
async function getHandler() {
    const user = await requireAuthenticatedUser();
    return sectionResponse(() => getPortfolioSummary(user.id), null as PortfolioSummary | null);
}

export const GET = withAuthErrors(getHandler);
