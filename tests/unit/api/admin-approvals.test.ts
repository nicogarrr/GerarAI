/**
 * Tests reales de las rutas admin de aprobación: claim CAS con fence
 * (pending->processing->decided->applied) en Mongo standalone.
 * - GET nunca decide (escáneres); POST con el botón decide.
 * - Solo el ganador del claim toca al usuario; un request viejo con claim
 *   retomado no finaliza nada (fence claimId).
 * - user=approved SOLO tras la decisión persistida; un fallo al aplicar es
 *   fail-closed y el reintento reconcilia (sin rollback tragado).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

const { connectToDatabase, findById, findOneAndUpdate, approvalUpdateOne, userUpdateOne, userFindOne, sessionDeleteMany, notifyAccountApproved } = vi.hoisted(() => ({
    connectToDatabase: vi.fn(),
    findById: vi.fn(),
    findOneAndUpdate: vi.fn(),
    approvalUpdateOne: vi.fn(),
    userUpdateOne: vi.fn(),
    userFindOne: vi.fn(),
    sessionDeleteMany: vi.fn(),
    notifyAccountApproved: vi.fn(),
}));
vi.mock('@/database/mongoose', () => ({ connectToDatabase }));
vi.mock('@/database/models/account-approval.model', () => ({
    AccountApproval: { findById, findOneAndUpdate, updateOne: approvalUpdateOne },
}));
vi.mock('@/lib/auth/approval-notify', () => ({ notifyAccountApproved }));

import { GET, POST } from '@/app/api/admin/approvals/decide/route';
import { createDecisionToken } from '@/lib/auth/account-approval';

const SECRET = 'test-secret-de-al-menos-32-caracteres';
const APPROVAL_ID = '507f1f77bcf86cd799439011';
const USER_ID = '507f1f77bcf86cd799439022';
const RECORD = { _id: APPROVAL_ID, userId: USER_ID, email: 'nuevo@e.co', name: 'Nuevo', decidedAt: null, decision: null, processingAt: null, processingAction: null, claimId: null, appliedAt: null };

function url(token?: string): string {
    return `http://localhost/api/admin/approvals/decide${token ? `?token=${token}` : ''}`;
}
function postWithToken(token: string): NextRequest {
    const body = new URLSearchParams({ token });
    return new NextRequest('http://localhost/api/admin/approvals/decide', { method: 'POST', body });
}
function tokenFor(action: 'approve' | 'reject'): string {
    return createDecisionToken({ approvalId: APPROVAL_ID, action, secret: SECRET });
}

beforeEach(() => {
    vi.clearAllMocks();
    process.env.BETTER_AUTH_SECRET = SECRET;
    connectToDatabase.mockResolvedValue({
        connection: {
            db: {
                collection: (name: string) =>
                    name === 'user' ? { updateOne: userUpdateOne, findOne: userFindOne } : { deleteMany: sessionDeleteMany },
            },
        },
    });
    findById.mockResolvedValue({ ...RECORD });
    findOneAndUpdate.mockResolvedValue({ ...RECORD, processingAt: new Date(), processingAction: 'approve', claimId: 'fence-1' });
    approvalUpdateOne.mockResolvedValue({ matchedCount: 1 });
    userFindOne.mockResolvedValue({ _id: USER_ID, accountStatus: 'pending' });
    userUpdateOne.mockResolvedValue({ matchedCount: 1, modifiedCount: 1 });
    notifyAccountApproved.mockResolvedValue(true);
});

describe('GET: confirmación, nunca decide (escáneres)', () => {
    it('formulario POST y NO toca nada', async () => {
        const res = await GET(new NextRequest(url(tokenFor('approve'))));
        expect(res.status).toBe(200);
        expect(await res.text()).toContain('method="post"');
        expect(findOneAndUpdate).not.toHaveBeenCalled();
        expect(userUpdateOne).not.toHaveBeenCalled();
    });

    it('con la cookie de inglés, la confirmación sale en inglés; sin ella, en español', async () => {
        const en = await GET(new NextRequest(url(tokenFor('approve')), { headers: { cookie: 'gerarai_locale=en' } }));
        const html = await en.text();
        expect(html).toContain('<html lang="en">');
        expect(html).toContain('Confirm: approve');
        expect(html).toContain('You are about to <strong>approve</strong> the account');
        expect(html).not.toContain('Confirmar');
        const es = await (await GET(new NextRequest(url(tokenFor('approve'))))).text();
        expect(es).toContain('<html lang="es">');
        expect(es).toContain('Confirmar: aprobar');
    });

    it('token manipulado: 400 sin tocar nada', async () => {
        const res = await GET(new NextRequest(url(tokenFor('approve').replace('.approve.', '.reject.'))));
        expect(res.status).toBe(400);
        expect(findById).not.toHaveBeenCalled();
    });

    it('decidida y aplicada: 410 sin tocar nada', async () => {
        findById.mockResolvedValue({ ...RECORD, decidedAt: new Date(), decision: 'approved', appliedAt: new Date() });
        const res = await GET(new NextRequest(url(tokenFor('reject'))));
        expect(res.status).toBe(410);
        expect(userUpdateOne).not.toHaveBeenCalled();
    });

    it('decidida SIN aplicar (ventana de crash): ofrece reconciliar, no un 410 seco', async () => {
        findById.mockResolvedValue({ ...RECORD, decidedAt: new Date(), decision: 'approved', appliedAt: null });
        const res = await GET(new NextRequest(url(tokenFor('approve'))));
        expect(res.status).toBe(200);
        expect(await res.text()).toContain('Aplicar la decisión registrada');
    });

    it('claim vivo de otro intento: 409 sin formulario', async () => {
        findById.mockResolvedValue({ ...RECORD, processingAt: new Date(), processingAction: 'approve' });
        const res = await GET(new NextRequest(url(tokenFor('reject'))));
        expect(res.status).toBe(409);
        expect(await res.text()).not.toContain('method="post"');
    });
});

describe('POST: claim CAS con fence, decisión persistida antes de tocar al usuario', () => {
    it('aprueba: claim -> finalize(decided) -> user=approved; avisa al usuario', async () => {
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(200);
        // Claim con fence aleatorio.
        expect(findOneAndUpdate).toHaveBeenCalledTimes(1);
        expect(findOneAndUpdate.mock.calls[0][0]).toMatchObject({ _id: APPROVAL_ID, decidedAt: null });
        const claimId = findOneAndUpdate.mock.calls[0][1].$set.claimId;
        expect(typeof claimId).toBe('string');
        // Finalize exige el fence y va ANTES de tocar al usuario.
        const finalize = approvalUpdateOne.mock.calls[0];
        expect(finalize[0]).toEqual({ _id: APPROVAL_ID, claimId, decidedAt: null });
        expect(finalize[1].$set.decision).toBe('approved');
        expect(userUpdateOne.mock.calls[0][1]).toEqual({ $set: { accountStatus: 'approved' } });
        expect(notifyAccountApproved).toHaveBeenCalledWith({ email: 'nuevo@e.co', name: 'Nuevo' });
    });

    it('rechaza: revoca sesiones al aplicar', async () => {
        const res = await POST(postWithToken(tokenFor('reject')));
        expect(res.status).toBe(200);
        expect(sessionDeleteMany).toHaveBeenCalledTimes(1);
        expect(notifyAccountApproved).not.toHaveBeenCalled();
    });

    it('fence: un request viejo cuyo claim fue retomado NO escribe nada', async () => {
        approvalUpdateOne.mockResolvedValueOnce({ matchedCount: 0 }); // finalize pierde el fence
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(409);
        expect(userUpdateOne).not.toHaveBeenCalled();
        expect(sessionDeleteMany).not.toHaveBeenCalled();
    });

    it('carrera approve/reject: el perdedor del claim NUNCA toca al usuario', async () => {
        findOneAndUpdate.mockResolvedValue(null); // claim ganado por otro (reject)
        findById.mockResolvedValue({ ...RECORD, processingAt: new Date(), processingAction: 'reject' });
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(409);
        expect(userUpdateOne).not.toHaveBeenCalled();
        expect(approvalUpdateOne).not.toHaveBeenCalled();
    });

    it('fallo de DB al aplicar tras decidir: fail-closed, NO libera ni dice "nada decidido"', async () => {
        userFindOne.mockRejectedValue(new Error('DB caída'));
        vi.spyOn(console, 'error').mockImplementation(() => {});
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(500);
        const html = await res.text();
        expect(html).toContain('aplicación pendiente');
        expect(html).not.toContain('Nada quedó decidido');
        // La decisión sigue persistida; nunca se revierte al usuario a pending.
        expect(userUpdateOne).not.toHaveBeenCalled();
        // Solo el finalize tocó el registro (no hay release tras decidir).
        expect(approvalUpdateOne).toHaveBeenCalledTimes(1);
    });

    it('reintento (decidida sin aplicar): reconcilia aplicando Y avisa al usuario (fleco del piloto)', async () => {
        findOneAndUpdate.mockResolvedValue(null); // claim: ya decidida
        findById.mockResolvedValue({ ...RECORD, decidedAt: new Date(), decision: 'approved', appliedAt: null, userNotifiedAt: null });
        userFindOne.mockResolvedValue({ _id: USER_ID, accountStatus: 'pending' });
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(200);
        expect(userUpdateOne).toHaveBeenCalledTimes(1);
        expect(userUpdateOne.mock.calls[0][1]).toEqual({ $set: { accountStatus: 'approved' } });
        // Marca appliedAt al reconciliar.
        expect(approvalUpdateOne.mock.calls.some((c) => c[1].$set?.appliedAt)).toBe(true);
        // El aviso sale también desde el reintento, con claim CAS de una sola vez.
        expect(notifyAccountApproved).toHaveBeenCalledWith({ email: 'nuevo@e.co', name: 'Nuevo' });
        expect(approvalUpdateOne.mock.calls.some((c) => c[0]?.userNotifiedAt === null && c[1].$set?.userNotifiedAt)).toBe(true);
    });

    it('aviso pendiente con aplicación hecha: el reintento solo manda el correo (una vez)', async () => {
        findOneAndUpdate.mockResolvedValue(null);
        findById.mockResolvedValue({ ...RECORD, decidedAt: new Date(), decision: 'approved', appliedAt: new Date(), userNotifiedAt: null });
        userFindOne.mockResolvedValue({ _id: USER_ID, accountStatus: 'approved' });
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(200);
        expect(userUpdateOne).not.toHaveBeenCalled();
        expect(notifyAccountApproved).toHaveBeenCalledTimes(1);
        expect(await res.text()).toContain('avisado por email');
    });

    it('aviso fallido en el reintento: claim liberado para poder reintentar', async () => {
        findOneAndUpdate.mockResolvedValue(null);
        findById.mockResolvedValue({ ...RECORD, decidedAt: new Date(), decision: 'approved', appliedAt: new Date(), userNotifiedAt: null });
        userFindOne.mockResolvedValue({ _id: USER_ID, accountStatus: 'approved' });
        notifyAccountApproved.mockResolvedValue(false);
        vi.spyOn(console, 'warn').mockImplementation(() => {});
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(200);
        expect(await res.text()).toContain('No se le pudo avisar por email');
        expect(approvalUpdateOne.mock.calls.some((c) => c[1].$unset?.userNotifiedAt !== undefined)).toBe(true);
    });

    it('replay ya consistente y avisado: 410 sin escribir ni reenviar el correo', async () => {
        findOneAndUpdate.mockResolvedValue(null);
        findById.mockResolvedValue({ ...RECORD, decidedAt: new Date(), decision: 'approved', appliedAt: new Date(), userNotifiedAt: new Date() });
        userFindOne.mockResolvedValue({ _id: USER_ID, accountStatus: 'approved' });
        // El CAS real fallaría con userNotifiedAt ya puesto; el mock lo respeta.
        approvalUpdateOne.mockImplementation((filter: Record<string, unknown>) =>
            Promise.resolve({ matchedCount: filter?.userNotifiedAt === null ? 0 : 1 }));
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(410);
        expect(userUpdateOne).not.toHaveBeenCalled();
        expect(notifyAccountApproved).not.toHaveBeenCalled();
    });

    it('cuenta borrada tras decidir: la decisión persiste, no hay crash', async () => {
        userFindOne.mockResolvedValue(null);
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(200);
        expect(notifyAccountApproved).not.toHaveBeenCalled();
    });

    it('token inválido: 400 sin claim ni escrituras', async () => {
        const res = await POST(postWithToken('firma-falsa'));
        expect(res.status).toBe(400);
        expect(findOneAndUpdate).not.toHaveBeenCalled();
        expect(userUpdateOne).not.toHaveBeenCalled();
    });

    it('aviso fallido: la aprobación cuenta y la página lo dice', async () => {
        notifyAccountApproved.mockResolvedValue(false);
        vi.spyOn(console, 'warn').mockImplementation(() => {});
        const res = await POST(postWithToken(tokenFor('approve')));
        expect(res.status).toBe(200);
        expect(await res.text()).toContain('No se le pudo avisar por email');
    });
});
