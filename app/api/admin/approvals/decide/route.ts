import { randomBytes } from 'node:crypto';

import { NextRequest, NextResponse } from 'next/server';
import { ObjectId } from 'mongodb';

import { connectToDatabase } from '@/database/mongoose';
import { AccountApproval, type AccountApprovalDoc } from '@/database/models/account-approval.model';
import { verifyDecisionToken, type ApprovalAction } from '@/lib/auth/account-approval';
import { notifyAccountApproved } from '@/lib/auth/approval-notify';
import { LOCALE_COOKIE, parseLocale, type Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * Enlaces aprobar/rechazar del correo de aviso a Nico.
 *
 * GET nunca decide: los escáneres de enlaces del correo precargan URLs y un
 * GET con efecto aprobaría o rechazaría sin Nico. GET muestra confirmación;
 * solo el POST del botón (con el mismo token) decide.
 *
 * Atomicidad en Mongo standalone (sin transacciones), claim CAS con FENCE:
 *   pending -> processing (claimId aleatorio por intento) -> decided -> applied.
 * - Solo el GANADOR del claim escribe, y su finalize exige su claimId: un
 *   request viejo cuyo claim fue retomado (caducado a los CLAIM_STALE_MS) no
 *   puede finalizar ni liberar el claim del nuevo dueño.
 * - user.accountStatus = approved/rejected SOLO tras la decisión persistida:
 *   primero se graba la decisión, después se aplica al usuario. Un fallo en
 *   ese segundo paso es fail-closed (la cuenta sigue pending) y el reintento
 *   reconcilia (aplicar la decisión ya registrada), nunca al revés.
 * - No hay rollback que trague errores: si la compensación no procede, el
 *   estado explícito es "decidida, pendiente de aplicar" (appliedAt null) y
 *   el listado admin la muestra con su enlace de aplicar.
 */

const CLAIM_STALE_MS = 2 * 60 * 1000;

function escapeHtml(value: string): string {
    return value
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

/** Idioma de la página: la cookie de Ajustes → Idioma si el navegador la lleva; si no, español. */
function requestT(request: NextRequest): { t: TranslateFn; locale: Locale } {
    const locale = parseLocale(request.cookies.get(LOCALE_COOKIE)?.value);
    return { t: createTranslator(locale), locale };
}

function page(title: string, bodyHtml: string, status: number, locale: Locale = 'es'): NextResponse {
    const html = [
        `<!doctype html><html lang="${locale}"><head><meta charset="utf-8">`,
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        `<title>${escapeHtml(title)} - GerarAI</title></head>`,
        '<body style="font-family: system-ui, sans-serif; max-width: 32rem; margin: 4rem auto; padding: 0 1rem;">',
        `<h1>${escapeHtml(title)}</h1>`,
        bodyHtml,
        '</body></html>',
    ].join('');
    return new NextResponse(html, {
        status,
        headers: { 'content-type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
    });
}

const ACTION_COPY = {
    approve: { verb: 'auth.approvals.verb.approve', done: 'auth.approvals.done.approved' },
    reject: { verb: 'auth.approvals.verb.reject', done: 'auth.approvals.done.rejected' },
} as const satisfies Record<ApprovalAction, { verb: string; done: string }>;

function decidedCopy(decision: unknown, t: TranslateFn): string {
    return decision === 'approved' ? t('auth.approvals.done.approved') : t('auth.approvals.done.rejected');
}

type ApplyResult = 'applied' | 'already' | 'missing-user' | 'failed';

/**
 * Aplica la decisión REGISTRADA al usuario (idempotente). La decisión es la
 * verdad; esto solo la refleja. Al rechazar revoca las sesiones abiertas.
 */
async function applyDecisionToUser(record: AccountApprovalDoc): Promise<ApplyResult> {
    const mongoose = await connectToDatabase();
    const db = mongoose?.connection?.db;
    if (!db || !record.decision || !ObjectId.isValid(record.userId)) return 'failed';
    const userId = new ObjectId(record.userId);
    try {
        const user = await db.collection('user').findOne({ _id: userId }, { projection: { accountStatus: 1 } });
        if (!user) return 'missing-user';
        if (user.accountStatus === record.decision) {
            if (!record.appliedAt) {
                await AccountApproval.updateOne({ _id: record._id }, { $set: { appliedAt: new Date() } });
            }
            return 'already';
        }
        const updated = await db.collection('user').updateOne({ _id: userId }, { $set: { accountStatus: record.decision } });
        if (updated.matchedCount !== 1) return 'missing-user';
        if (record.decision === 'rejected') {
            await db.collection('session').deleteMany({ userId });
        }
        await AccountApproval.updateOne({ _id: record._id }, { $set: { appliedAt: new Date() } });
        return 'applied';
    } catch (error) {
        console.error('[approvals] no se pudo aplicar la decisión registrada (reintentable):', error instanceof Error ? error.message : error);
        return 'failed';
    }
}

/**
 * Aviso de cuenta aprobada UNA sola vez: claim CAS sobre userNotifiedAt antes de
 * enviar (dos reconciliaciones concurrentes no duplican el correo). Si el
 * envío falla, el claim se libera para que un reintento pueda avisar; la
 * aprobación en sí nunca depende del correo.
 */
async function notifyApprovedOnce(record: AccountApprovalDoc): Promise<'sent' | 'already' | 'failed'> {
    if (record.decision !== 'approved') return 'already';
    const claim = await AccountApproval.updateOne(
        { _id: record._id, userNotifiedAt: null },
        { $set: { userNotifiedAt: new Date() } },
    ).catch(() => null);
    if (!claim || claim.matchedCount !== 1) return 'already';
    const sent = await notifyAccountApproved({ email: record.email, name: record.name }).catch(() => false);
    if (!sent) {
        await AccountApproval.updateOne({ _id: record._id }, { $unset: { userNotifiedAt: '' } }).catch(() => null);
        return 'failed';
    }
    return 'sent';
}

function noticeCopy(notice: 'sent' | 'already' | 'failed', t: TranslateFn): string {
    if (notice === 'sent') return t('auth.approvals.noticeSent');
    if (notice === 'failed') return t('auth.approvals.noticeFailed');
    return '';
}

/** GET: solo confirmación (y, si procede, reconciliación). No decide nada. */
export async function GET(request: NextRequest) {
    const { t, locale } = requestT(request);
    const view = (title: string, bodyHtml: string, status: number) => page(title, bodyHtml, status, locale);
    const token = request.nextUrl.searchParams.get('token');
    const payload = verifyDecisionToken(token, process.env.BETTER_AUTH_SECRET);
    if (!payload) {
        return view(t('auth.approvals.invalidTitle'), `<p>${t('auth.approvals.invalidDecideGet')}</p>`, 400);
    }
    await connectToDatabase();
    const record = await AccountApproval.findById(payload.approvalId).catch(() => null);
    if (!record) {
        return view(t('auth.approvals.notFoundTitle'), `<p>${t('auth.approvals.notFound')}</p>`, 404);
    }
    if (record.decidedAt) {
        if (record.appliedAt) {
            return view(t('auth.approvals.decidedTitle'), `<p>${t('auth.approvals.alreadyDecidedOnce', { email: escapeHtml(record.email), decision: decidedCopy(record.decision, t) })}</p>`, 410);
        }
        // Decidida pero sin aplicar (ventana de crash): ofrecer reconciliar.
        const form = [
            `<p>${t('auth.approvals.recordedNotApplied', { email: escapeHtml(record.email), decision: decidedCopy(record.decision, t) })}</p>`,
            '<form method="post" action="/api/admin/approvals/decide">',
            `<input type="hidden" name="token" value="${escapeHtml(token ?? '')}">`,
            `<button type="submit" style="font-size: 1rem; padding: 0.6rem 1.2rem;">${t('auth.approvals.applyButton')}</button>`,
            '</form>',
        ].join('');
        return view(t('auth.approvals.applyTitle'), form, 200);
    }
    if (record.processingAt && Date.now() - new Date(record.processingAt).getTime() < CLAIM_STALE_MS) {
        return view(t('auth.approvals.inProgressTitle'), `<p>${t('auth.approvals.inProgress')}</p>`, 409);
    }
    const verb = t(ACTION_COPY[payload.action].verb);
    const form = [
        `<p>${t('auth.approvals.confirmBody', { verb, email: escapeHtml(record.email), name: record.name ? ` (${escapeHtml(record.name)})` : '' })}</p>`,
        '<form method="post" action="/api/admin/approvals/decide">',
        `<input type="hidden" name="token" value="${escapeHtml(token ?? '')}">`,
        `<button type="submit" style="font-size: 1rem; padding: 0.6rem 1.2rem;">${t('auth.approvals.confirmButton', { verb })}</button>`,
        '</form>',
    ].join('');
    return view(t('auth.approvals.confirmTitle', { verb }), form, 200);
}

/** POST: decide de verdad. Claim CAS con fence; decisión persistida antes de tocar al usuario. */
export async function POST(request: NextRequest) {
    const { t, locale } = requestT(request);
    const view = (title: string, bodyHtml: string, status: number) => page(title, bodyHtml, status, locale);
    const form = await request.formData().catch(() => null);
    const rawToken = form?.get('token');
    const payload = verifyDecisionToken(
        typeof rawToken === 'string' ? rawToken : null,
        process.env.BETTER_AUTH_SECRET,
    );
    if (!payload) {
        return view(t('auth.approvals.invalidTitle'), `<p>${t('auth.approvals.invalidDecidePost')}</p>`, 400);
    }
    const done = t(ACTION_COPY[payload.action].done);
    const desired = payload.action === 'approve' ? 'approved' : 'rejected';

    await connectToDatabase();

    // 1) Claim atómico pending -> processing con FENCE (claimId aleatorio por
    // intento). Un claim muerto de hace CLAIM_STALE_MS puede retomarse.
    const claimId = randomBytes(8).toString('hex');
    const claimed = await AccountApproval.findOneAndUpdate(
        {
            _id: payload.approvalId,
            decidedAt: null,
            $or: [{ processingAt: null }, { processingAt: { $lt: new Date(Date.now() - CLAIM_STALE_MS) } }],
        },
        { $set: { processingAt: new Date(), processingAction: payload.action, claimId } },
        { new: true },
    ).catch(() => null);
    if (!claimed) {
        const existing = await AccountApproval.findById(payload.approvalId).catch(() => null);
        if (!existing) {
            return view(t('auth.approvals.notFoundTitle'), `<p>${t('auth.approvals.notFound')}</p>`, 404);
        }
        if (!existing.decidedAt) {
            return view(t('auth.approvals.inProgressTitle'), `<p>${t('auth.approvals.inProgress')}</p>`, 409);
        }
        // Ya decidida: reconciliar si la aplicación quedó a medias (el enlace
        // estaba consumido pero el usuario no reflejó la decisión).
        const applied = await applyDecisionToUser(existing);
        if (applied === 'failed') {
            return view(t('auth.approvals.pendingTitle'), `<p>${t('auth.approvals.pendingRetry', { decision: decidedCopy(existing.decision, t) })}</p>`, 500);
        }
        // El reintento reconciliador también avisa al usuario: si la primera
        // pasada aplicó pero el correo no salió, aquí sale (una sola vez).
        // Cuenta borrada: no tiene sentido avisar por email de un acceso que ya no existe.
        const notice = applied === 'missing-user' ? 'already' : await notifyApprovedOnce(existing);
        if (notice === 'failed') {
            console.warn(`[approvals] cuenta ${existing.userId} aprobada sin poder avisar al usuario por email`);
        }
        const extra = noticeCopy(notice, t);
        if (applied === 'applied') {
            return view(t('auth.approvals.appliedTitle'), `<p>${t('auth.approvals.appliedNow', { email: escapeHtml(existing.email), decision: decidedCopy(existing.decision, t), extra })}</p>`, 200);
        }
        if (notice !== 'already') {
            return view(t('auth.approvals.decidedTitle'), `<p>${t('auth.approvals.alreadyApplied', { email: escapeHtml(existing.email), decision: decidedCopy(existing.decision, t), extra })}</p>`, 200);
        }
        return view(t('auth.approvals.decidedTitle'), `<p>${t('auth.approvals.alreadyDecidedOnce', { email: escapeHtml(existing.email), decision: decidedCopy(existing.decision, t) })}</p>`, 410);
    }

    // 2) Persistir la decisión PRIMERO, con fence: si matchedCount !== 1 este
    // request perdió su claim (retomado por uno más reciente) y no escribe NADA.
    const finalized = await AccountApproval.updateOne(
        { _id: claimed._id, claimId, decidedAt: null },
        { $set: { decidedAt: new Date(), decision: desired }, $unset: { processingAt: '', processingAction: '', claimId: '' } },
    );
    if (finalized.matchedCount !== 1) {
        return view(t('auth.approvals.inProgressTitle'), `<p>${t('auth.approvals.inProgressNewer')}</p>`, 409);
    }

    // 3) Decisión ya persistida: AHORA aplicar al usuario. Fallo = fail-closed
    // (la cuenta sigue pending) y el reintento reconcilia; jamás un rollback
    // que deje approved sin decisión registrada.
    const applied = await applyDecisionToUser(
        Object.assign(claimed, { decision: desired, appliedAt: null }),
    );
    if (applied === 'failed') {
        return view(t('auth.approvals.pendingTitle'), `<p>${t('auth.approvals.pendingReopen', { decision: done })}</p>`, 500);
    }

    // 4) Aviso al usuario al aprobar (fail-closed honesto: si el SMTP no está,
    // la aprobación cuenta igualmente y la página lo dice).
    let extra = '';
    if (payload.action === 'approve' && (applied === 'applied' || applied === 'already')) {
        const notice = await notifyApprovedOnce(claimed);
        if (notice === 'failed') {
            console.warn(`[approvals] cuenta ${claimed.userId} aprobada sin poder avisar al usuario por email`);
        }
        extra = noticeCopy(notice, t);
    }

    return view(
        payload.action === 'approve' ? t('auth.approvals.approvedTitle') : t('auth.approvals.rejectedTitle'),
        `<p>${t('auth.approvals.result', { email: escapeHtml(claimed.email), decision: done, extra })}</p>`,
        200,
    );
}
