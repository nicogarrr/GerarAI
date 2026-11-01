import { beforeEach, describe, expect, it, vi } from 'vitest';

const { connectToDatabase, findOne, updateOne, countDocuments, create, clientIp, hashIp, notifyAccessRequest, headers } = vi.hoisted(() => ({
    connectToDatabase: vi.fn(),
    findOne: vi.fn(),
    updateOne: vi.fn(),
    countDocuments: vi.fn(),
    create: vi.fn(),
    clientIp: vi.fn(),
    hashIp: vi.fn(),
    notifyAccessRequest: vi.fn(),
    headers: vi.fn(),
}));
vi.mock('next/headers', () => ({ headers }));
vi.mock('@/database/mongoose', () => ({ connectToDatabase }));
vi.mock('@/database/models/access-request.model', () => ({
    AccessRequest: { findOne, updateOne, countDocuments, create },
}));
vi.mock('@/lib/access-request-ip', () => ({ clientIp, hashIp }));
vi.mock('@/lib/access-request-notify', () => ({ notifyAccessRequest }));
vi.mock('@/lib/research/backend-error-locale', () => ({ requestLocale: async () => 'en' }));

import { requestAccess } from '@/lib/actions/access-request.actions';

const input = { name: 'Nico', email: 'NICO@Example.com', note: 'I want to try it', honeypot: '' };

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    headers.mockResolvedValue(new Headers({ 'x-forwarded-for': '1.2.3.4' }));
    clientIp.mockReturnValue('1.2.3.4');
    hashIp.mockReturnValue('ip-hash-1');
    findOne.mockResolvedValue(null);
    countDocuments.mockResolvedValue(0);
    create.mockResolvedValue({ _id: 'doc1' });
    notifyAccessRequest.mockResolvedValue(true);
});

describe('solicitud de acceso en inglés', () => {
    it('recibida y validación en inglés', async () => {
        expect(await requestAccess(input)).toEqual({ ok: true, message: 'Request received. We review access in batches and will write to the email you gave us.' });
        expect(await requestAccess({ ...input, name: 'N' })).toEqual({ ok: false, field: 'name', message: 'Enter your name.' });
        expect(await requestAccess({ ...input, email: 'nope' })).toEqual({ ok: false, field: 'email', message: 'Enter a valid email.' });
        expect(await requestAccess({ ...input, note: 'x'.repeat(501) })).toEqual({ ok: false, field: 'note', message: 'The note can be up to 500 characters.' });
    });
    it('límite por conexión y fallo al guardar en inglés', async () => {
        countDocuments.mockResolvedValue(99);
        expect(await requestAccess(input)).toEqual({ ok: false, message: 'Too many requests from your connection. Try again later.' });
        countDocuments.mockResolvedValue(0);
        create.mockRejectedValue(new Error('db down'));
        expect(await requestAccess(input)).toEqual({ ok: false, message: "We couldn't save the request right now. Try again in a few minutes." });
    });
});
