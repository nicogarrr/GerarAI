// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const m = vi.hoisted(() => ({
    requireUser: vi.fn(),
    callAuth: vi.fn(),
    identity: vi.fn(),
    connect: vi.fn(),
    residue: vi.fn(),
    createToken: vi.fn(),
    getSession: vi.fn(),
    accessDelete: vi.fn(),
    accountDelete: vi.fn(),
    tradeDelete: vi.fn(),
}));

vi.mock('next/headers', () => ({ headers: async () => new Headers() }));
vi.mock('@/lib/better-auth/auth', () => ({ getAuth: async () => ({ api: { getSession: m.getSession } }) }));
vi.mock('@/lib/auth/endpoint', () => ({ callAuthEndpoint: m.callAuth }));
vi.mock('@/lib/auth/delete-reauth', () => ({ DELETE_REAUTH_HEADER: 'x-delete-reauth', createDeleteReauthToken: m.createToken }));
vi.mock('@/lib/better-auth/account-residue', () => ({ deleteAuthAccountResidue: m.residue }));
vi.mock('@/lib/auth/research-identity', () => ({ researchIdentityHeaders: m.identity }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: m.requireUser }));
vi.mock('@/database/mongoose', () => ({ connectToDatabase: m.connect }));
vi.mock('@/lib/env', () => ({ env: { BETTER_AUTH_SECRET: 'secret-xyz' } }));
vi.mock('@/database/models/access-request.model', () => ({ AccessRequest: { deleteMany: m.accessDelete } }));
vi.mock('@/database/models/manual-demo.model', () => ({
    ManualDemoAccount: { deleteMany: m.accountDelete },
    ManualDemoTrade: { deleteMany: m.tradeDelete },
}));

import { AppError } from '@/lib/types/errors';
import { deleteAccount, exportAccountData } from '@/lib/actions/privacy.actions';

const USER = { id: 'u1', email: 'Nico@Example.com', name: 'Nico' };
const okResponse = (body: unknown = {}, status = 200) => new Response(JSON.stringify(body), { status });
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    m.requireUser.mockResolvedValue(USER);
    m.callAuth.mockResolvedValue({});
    m.identity.mockResolvedValue({ 'x-research-user': 'u1' });
    m.connect.mockResolvedValue({ connection: { db: {} } });
    m.residue.mockResolvedValue(undefined);
    m.createToken.mockReturnValue('reauth-token');
    m.getSession.mockResolvedValue({ user: { email: 'nico@example.com', name: 'Nico', country: 'ES' } });
    m.accessDelete.mockResolvedValue({});
    m.accountDelete.mockResolvedValue({});
    m.tradeDelete.mockResolvedValue({});
    fetchMock = vi.fn(async () => okResponse());
    vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
    vi.unstubAllGlobals();
    Object.values(m).forEach((f) => f.mockReset());
});

describe('deleteAccount - validaciones previas (no se toca nada)', () => {
    it('sin email en sesión no borra nada', async () => {
        m.requireUser.mockResolvedValue({ id: 'u1', email: '  ' });
        const r = await deleteAccount({ confirmation: 'x', password: 'p' });
        expect(r.success).toBe(false);
        expect(m.callAuth).not.toHaveBeenCalled();
        expect(fetchMock).not.toHaveBeenCalled();
    });
    it('la frase de confirmación debe ser el email de la sesión (sin distinguir mayúsculas/espacios)', async () => {
        const bad = await deleteAccount({ confirmation: 'otro@example.com', password: 'p' });
        expect(bad).toEqual({ success: false, message: 'Escribe exactamente el email de tu cuenta para confirmar.' });
        expect(m.callAuth).not.toHaveBeenCalled();
        expect(fetchMock).not.toHaveBeenCalled();
    });
    it('sin contraseña pide reautenticación y no llama al backend', async () => {
        const r = await deleteAccount({ confirmation: ' nico@example.com ', password: '' });
        expect(r.success).toBe(false);
        expect(r.message).toContain('contraseña');
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('deleteAccount - reautenticación', () => {
    it.each([
        [401, 'Contraseña incorrecta. No se ha borrado nada.'],
        [400, 'Contraseña incorrecta. No se ha borrado nada.'],
        [429, 'Demasiados intentos. Espera un momento antes de volver a intentarlo.'],
        [500, 'No se pudo verificar la sesión. No se ha borrado nada; inténtalo de nuevo.'],
    ])('verify-password con %i no destruye nada', async (status, message) => {
        m.callAuth.mockRejectedValueOnce(new AppError('x', 'AUTH', status));
        const r = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r).toEqual({ success: false, message });
        expect(fetchMock).not.toHaveBeenCalled();
        expect(m.accessDelete).not.toHaveBeenCalled();
    });
});

describe('deleteAccount - orden de destrucción', () => {
    it('backend caído: no borra Mongo ni la cuenta', async () => {
        fetchMock.mockRejectedValueOnce(new Error('ECONNREFUSED'));
        const r = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r.success).toBe(false);
        expect(r.message).toContain('no se ha borrado nada');
        expect(m.accessDelete).not.toHaveBeenCalled();
        expect(m.callAuth).toHaveBeenCalledTimes(1); // solo verify-password
    });
    it('backend 502 pide reintento; otro error no afirma borrado', async () => {
        fetchMock.mockResolvedValueOnce(okResponse({}, 502));
        const r502 = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r502.message).toContain('no se ha confirmado el borrado');
        fetchMock.mockResolvedValueOnce(okResponse({}, 500));
        const r500 = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r500.message).toBe('No se pudo borrar la cuenta. No se ha eliminado nada. Inténtalo de nuevo.');
        expect(m.accessDelete).not.toHaveBeenCalled();
    });
    it('falla la limpieza Mongo: aborta ANTES de borrar el usuario de Better Auth', async () => {
        m.tradeDelete.mockRejectedValueOnce(new Error('mongo down'));
        const r = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r.success).toBe(false);
        expect(r.message).toContain('datos auxiliares');
        expect(m.callAuth).toHaveBeenCalledTimes(1); // nunca llegó a /delete-user
    });
    it('falla /delete-user: informa que la cuenta de acceso sigue activa', async () => {
        m.callAuth.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('auth down'));
        const r = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r.success).toBe(false);
        expect(r.message).toContain('la cuenta de acceso sigue activa');
        expect(m.residue).not.toHaveBeenCalled();
    });
    it('falla la limpieza de residuos 2FA: no declara éxito', async () => {
        m.residue.mockRejectedValueOnce(new Error('x'));
        const r = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r.success).toBe(false);
        expect(r.message).toContain('doble factor');
    });
    it('sin db de Mongo en la limpieza final tampoco declara éxito', async () => {
        m.connect.mockResolvedValueOnce({ connection: { db: {} } }).mockResolvedValueOnce({ connection: {} });
        const r = await deleteAccount({ confirmation: 'nico@example.com', password: 'p' });
        expect(r.success).toBe(false);
    });
    it('camino feliz: borra solo datos del usuario firmado, en orden, con la frase fija y el token de reauth', async () => {
        const r = await deleteAccount({ confirmation: 'NICO@example.com', password: 'pw' });
        expect(r).toEqual({ success: true, message: 'Cuenta y datos eliminados. Se han cerrado todas las sesiones.' });
        // 1) verify-password, 2) backend DELETE, 3) Mongo, 4) delete-user, 5) residuos
        expect(m.callAuth.mock.calls[0]).toEqual(['/verify-password', { password: 'pw' }]);
        const [url, init] = fetchMock.mock.calls[0];
        expect(String(url)).toMatch(/\/api\/privacy\/account$/);
        expect(init.method).toBe('DELETE');
        expect(JSON.parse(init.body)).toEqual({ confirmation: 'ELIMINAR MI CUENTA' });
        expect(m.identity).toHaveBeenCalledWith({ method: 'DELETE', path: '/api/privacy/account', body: init.body });
        expect(m.accessDelete).toHaveBeenCalledWith({ email: 'nico@example.com' });
        expect(m.accountDelete).toHaveBeenCalledWith({ userId: 'u1' });
        expect(m.tradeDelete).toHaveBeenCalledWith({ userId: 'u1' });
        expect(m.createToken).toHaveBeenCalledWith('u1', 'secret-xyz');
        expect(m.callAuth.mock.calls[1]).toEqual(['/delete-user', { password: 'pw' }, { 'x-delete-reauth': 'reauth-token' }]);
        expect(m.residue).toHaveBeenCalledWith({}, USER);
    });
});

describe('exportAccountData', () => {
    it('devuelve JSON con el perfil de sesión añadido y nombre de fichero fechado', async () => {
        fetchMock.mockResolvedValueOnce(okResponse({ positions: [1], profile: { tier: 'x' } }));
        const r = await exportAccountData();
        expect(r.contentType).toBe('application/json');
        expect(r.filename).toMatch(/^gerarai-datos-\d{4}-\d{2}-\d{2}\.json$/);
        const parsed = JSON.parse(r.content);
        expect(parsed.positions).toEqual([1]);
        expect(parsed.profile.tier).toBe('x');
        expect(parsed.profile.account).toMatchObject({ email: 'nico@example.com', country: 'ES', riskTolerance: null });
        expect(m.identity).toHaveBeenCalledWith({ method: 'GET', path: '/api/privacy/export' });
    });
    it('si la sesión falla usa el usuario autenticado como perfil mínimo', async () => {
        m.getSession.mockRejectedValueOnce(new Error('x'));
        fetchMock.mockResolvedValueOnce(okResponse({ a: 1 }));
        const parsed = JSON.parse((await exportAccountData()).content);
        expect(parsed.profile.account).toEqual({ email: 'Nico@Example.com', name: 'Nico' });
    });
    it('backend inaccesible: error 503 tipado', async () => {
        fetchMock.mockRejectedValueOnce(new Error('x'));
        await expect(exportAccountData()).rejects.toMatchObject({ code: 'PRIVACY_BACKEND_UNAVAILABLE', statusCode: 503 });
    });
    it('backend responde error: propaga su estado sin devolver datos', async () => {
        fetchMock.mockResolvedValueOnce(okResponse({}, 500));
        await expect(exportAccountData()).rejects.toMatchObject({ code: 'PRIVACY_EXPORT_FAILED', statusCode: 500 });
    });
});
