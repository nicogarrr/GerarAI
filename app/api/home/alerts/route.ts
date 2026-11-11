import { withAuthErrors } from '@/lib/auth/route-auth';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import {
    getRecentTriggeredAlerts,
    getUserAlerts,
    type Alert,
    type TriggeredAlertDelivery,
} from '@/lib/actions/alerts.actions';
import { sectionResponse } from '@/lib/home/section-response';

/** Sección Alertas del inicio: reglas activas + últimas 3 disparadas. */
async function getHandler() {
    await requireAuthenticatedUser();
    return sectionResponse(
        () => Promise.all([getUserAlerts(), getRecentTriggeredAlerts(3)]).then(([rules, triggered]) => ({ rules, triggered })),
        { rules: [] as Alert[], triggered: [] as TriggeredAlertDelivery[] },
    );
}

export const GET = withAuthErrors(getHandler);
