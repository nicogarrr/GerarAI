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
 * /calendar/suscripcion: el origen del enlace de suscripción (que lleva el
 * token del feed en la URL) NO puede salir de una cabecera Host controlable:
 * solo el dominio propio, hosts locales de desarrollo o NEXT_PUBLIC_SITE_URL.
 * Un host ajeno, aunque sea sintácticamente válido, cae al dominio propio.
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

    it('sin variable: dominio propio y proto saneados (primer valor de la lista)', async () => {
        headerValues = { 'x-forwarded-host': 'gerarai.duckdns.org, evil.example', 'x-forwarded-proto': 'https, http' };
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://gerarai.duckdns.org');
    });

    it('host ajeno aunque sea válido (evil.example) NO cuela: cae al dominio propio', async () => {
        headerValues = { host: 'evil.example' };
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://gerarai.duckdns.org');
    });

    it('host con sintaxis inválida o proto desconocido: cae al dominio propio en https', async () => {
        headerValues = { host: 'evil.example/?x=', 'x-forwarded-proto': 'javascript:' };
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://gerarai.duckdns.org');
    });

    it('localhost de desarrollo sí entra en la lista de confianza', async () => {
        headerValues = { host: 'localhost:3000', 'x-forwarded-proto': 'http' };
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('http://localhost:3000');
    });

    it('sin cabeceras útiles: dominio propio en https', async () => {
        render(await CalendarSubscriptionPage());
        expect(managerProps.origin).toBe('https://gerarai.duckdns.org');
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
