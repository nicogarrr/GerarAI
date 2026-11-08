// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
let headerValues: Record<string, string | null> = {};
vi.mock('next/headers', () => ({
    cookies: async () => ({ get: () => undefined }),
    headers: async () => ({ get: (name: string) => headerValues[name] ?? null }),
}));
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * /calendar/suscripcion: el origen del enlace de suscripción se construye con
 * saneado SINTÁCTICO de cabeceras (trim, primer valor de la lista forwarded,
 * proto solo http/https, dominio por defecto si la sintaxis no cuadra). OJO:
 * no hay allowlist — un host sintácticamente válido se acepta tal cual.
 * Un backend sin endpoint (404) se trata como caído.
 */
const getCalendarFeed = vi.fn();
vi.mock('@/lib/actions/calendar-feed.actions', () => ({ getCalendarFeed: () => getCalendarFeed() }));
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: () => false }));
vi.mock('@/components/system/BackendOffline', () => ({ default: () => <p>backend caído</p> }));

let managerProps: Record<string, unknown> = {};
vi.mock('@/components/calendar/SubscriptionManager', () => ({
    default: (props: Record<string, unknown>) => {
        managerProps = props;
        return <p>gestor de suscripción</p>;
    },
}));

import CalendarSubscriptionPage from '@/app/(root)/calendar/suscripcion/page';
import { AppError } from '@/lib/types/errors';

beforeEach(() => {
    managerProps = {};
    headerValues = {};
    getCalendarFeed.mockReset();
    getCalendarFeed.mockResolvedValue({ active: true, scope: 'followed', created_at: null, last_used_at: null });
    delete process.env.NEXT_PUBLIC_SITE_URL;
    delete process.env.BETTER_AUTH_URL;
});
afterEach(() => {
    delete process.env.NEXT_PUBLIC_SITE_URL;
    delete process.env.BETTER_AUTH_URL;
});

describe('página de suscripción al calendario', () => {
    it('con NEXT_PUBLIC_SITE_URL usa ese origen y le quita las barras finales', async () => {
        process.env.NEXT_PUBLIC_SITE_URL = 'https://gerarai.com///';
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://gerarai.com');
    });

    it('sin variable: host y proto de cabeceras saneados (primer valor de la lista)', async () => {
        headerValues = { 'x-forwarded-host': 'app.gerarai.com, evil.example', 'x-forwarded-proto': 'https, http' };
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://app.gerarai.com');
    });

    it('host con sintaxis inválida o proto desconocido: cae al dominio por defecto', async () => {
        headerValues = { host: 'evil.example/?x=', 'x-forwarded-proto': 'javascript:' };
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://gerarai.vercel.app');
    });

    it('un host sintácticamente válido se acepta tal cual (no hay allowlist)', async () => {
        headerValues = { host: 'otro-dominio.example' };
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://otro-dominio.example');
    });

    it('sin cabeceras útiles: dominio por defecto en https', async () => {
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://gerarai.vercel.app');
    });

    it('404 del backend (endpoint sin desplegar): pantalla de reintento como caído', async () => {
        getCalendarFeed.mockRejectedValue(new AppError('not found', 'RESEARCH_API_ERROR', 404));
        render(await CalendarSubscriptionPage());
        expect(screen.getByText('backend caído')).toBeInTheDocument();
    });

    it('otro error del backend se propaga, no se disfraza', async () => {
        getCalendarFeed.mockRejectedValue(new AppError('boom', 'RESEARCH_API_ERROR', 500));
        await expect(CalendarSubscriptionPage()).rejects.toThrow('boom');
    });

    it('estado de la suscripción llega al gestor', async () => {
        render(await CalendarSubscriptionPage());
        expect(managerProps.initialState).toEqual({ active: true, scope: 'followed', created_at: null, last_used_at: null });
    });
});
