import AccountStatusNotice from '@/components/auth/AccountStatusNotice';
import { parsePendingState } from '@/lib/auth/pending-account';

// El estado llega por querystring (?estado=pendiente|rechazada): la pagina es
// dinamica y no se prerenderiza con un estado fijo.
export const dynamic = 'force-dynamic';

type Props = {
    searchParams: Promise<{ estado?: string | string[] }>;
};

/**
 * Pantalla de estado para cuentas pendientes de aprobacion o rechazadas.
 * La ensenan los formularios de acceso tras el alta y el inicio de sesion, y
 * sirve de enlace directo (p. ej. desde un correo). Vive bajo (auth): una
 * cuenta pendiente no tiene sesion (autoSignIn=false y el hook de acceso la
 * rechaza), asi que el redirect del layout a /inicio no la tapa.
 */
export default async function CuentaPendiente({ searchParams }: Props) {
    const { estado } = await searchParams;
    return <AccountStatusNotice state={parsePendingState(estado)} />;
}
