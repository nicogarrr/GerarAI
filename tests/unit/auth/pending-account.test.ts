import { describe, expect, it } from 'vitest';

import {
    afterSignUpRoute,
    cuentaPendienteHref,
    parsePendingState,
    pendingStateFromSignInCode,
} from '@/lib/auth/pending-account';

// Registro abierto con aprobacion manual: la interfaz debe reconocer los
// codigos del contrato con el carril de backend y no confundirlos con un
// error generico de acceso.
describe('pendingStateFromSignInCode', () => {
    it('reconoce los codigos propagados por endpoint.ts', () => {
        expect(pendingStateFromSignInCode('AUTH_ENDPOINT_ACCOUNT_PENDING')).toBe('pendiente');
        expect(pendingStateFromSignInCode('AUTH_ENDPOINT_ACCOUNT_REJECTED')).toBe('rechazada');
    });

    it('reconoce los codigos crudos de la API por si cambia el prefijo', () => {
        expect(pendingStateFromSignInCode('ACCOUNT_PENDING')).toBe('pendiente');
        expect(pendingStateFromSignInCode('ACCOUNT_REJECTED')).toBe('rechazada');
    });

    it('ignora errores que no son de estado de cuenta', () => {
        expect(pendingStateFromSignInCode('AUTH_ENDPOINT_ERROR')).toBeNull();
        expect(pendingStateFromSignInCode('AUTH_UNAVAILABLE')).toBeNull();
        expect(pendingStateFromSignInCode('INVALID_CREDENTIALS')).toBeNull();
        expect(pendingStateFromSignInCode(undefined)).toBeNull();
        expect(pendingStateFromSignInCode('')).toBeNull();
    });
});

describe('afterSignUpRoute', () => {
    it('solo un approved explicito entra directo a la app', () => {
        expect(afterSignUpRoute('approved')).toBe('/inicio');
    });

    it('una cuenta nueva pendiente va a la pantalla de estado', () => {
        expect(afterSignUpRoute('pending')).toBe('pendiente');
    });

    it('sin accountStatus (backend antiguo) tambien va a la pantalla: no hay sesion usable', () => {
        expect(afterSignUpRoute(undefined)).toBe('pendiente');
        expect(afterSignUpRoute(null)).toBe('pendiente');
        expect(afterSignUpRoute('')).toBe('pendiente');
    });

    it('un rechazo en el alta muestra el estado rechazada', () => {
        expect(afterSignUpRoute('rejected')).toBe('rechazada');
    });
});

describe('cuentaPendienteHref y parsePendingState', () => {
    it('construye la ruta con el estado en el querystring', () => {
        expect(cuentaPendienteHref('pendiente')).toBe('/cuenta-pendiente?estado=pendiente');
        expect(cuentaPendienteHref('rechazada')).toBe('/cuenta-pendiente?estado=rechazada');
    });

    it('parsea el querystring y cualquier valor raro cae en pendiente', () => {
        expect(parsePendingState('rechazada')).toBe('rechazada');
        expect(parsePendingState(['rechazada'])).toBe('rechazada');
        expect(parsePendingState('pendiente')).toBe('pendiente');
        expect(parsePendingState('PENDIENTE')).toBe('pendiente');
        expect(parsePendingState(undefined)).toBe('pendiente');
        expect(parsePendingState(['rechazada', 'pendiente'])).toBe('rechazada');
    });
});
