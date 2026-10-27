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

import { requestAccess } from '@/lib/actions/access-request.actions';

const RECEIVED = 'Solicitud recibida. Revisamos el acceso por tandas y te escribiremos al correo que has indicado.';
const input = { name: 'Nico', email: 'NICO@Example.com', note: 'Quiero probarlo', honeypot: '' };

beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    headers.mockResolvedValue(new Headers({ 'x-forwarded-for': '1.2.3.4, 5.6.7.8' }));
    clientIp.mockReturnValue('1.2.3.4');
    hashIp.mockReturnValue('ip-hash-1');
    findOne.mockResolvedValue(null);
    countDocuments.mockResolvedValue(0);
    create.mockResolvedValue({ _id: 'doc1' });
    notifyAccessRequest.mockResolvedValue(true);
});

describe('validación antes de tocar la base de datos', () => {
    it('honeypot relleno (bot): misma respuesta que un humano, nada se guarda', async () => {
        const result = await requestAccess({ ...input, honeypot: 'http://spam' });
        expect(result).toEqual({ ok: true, message: RECEIVED });
        expect(connectToDatabase).not.toHaveBeenCalled();
    });

    it('nombre corto / email inválido / nota larga -> error con campo, sin BD', async () => {
        expect(await requestAccess({ ...input, name: 'N' })).toEqual({ ok: false, field: 'name', message: 'Escribe tu nombre.' });
        expect(await requestAccess({ ...input, email: 'no-es-email' })).toEqual({ ok: false, field: 'email', message: 'Introduce un email válido.' });
        const nota = 'x'.repeat(501);
        expect(await requestAccess({ ...input, note: nota })).toEqual({
            ok: false, field: 'note', message: 'La nota admite hasta 500 caracteres.',
        });
        expect(connectToDatabase).not.toHaveBeenCalled();
    });
});

describe('guardado y aviso, en ese orden', () => {
    it('solicitud nueva: normaliza el email, guarda con hash de IP y marca notifiedAt si el aviso salió', async () => {
        const result = await requestAccess(input);
        expect(result).toEqual({ ok: true, message: RECEIVED });
        expect(create).toHaveBeenCalledWith({ email: 'nico@example.com', name: 'Nico', note: 'Quiero probarlo', ipHash: 'ip-hash-1' });
        expect(clientIp).toHaveBeenCalledWith('1.2.3.4, 5.6.7.8', null);
        expect(notifyAccessRequest).toHaveBeenCalledWith({ name: 'Nico', email: 'nico@example.com', note: 'Quiero probarlo' }, 0);
        expect(updateOne).toHaveBeenCalledWith({ _id: 'doc1' }, { $set: { notifiedAt: expect.any(Date) } });
    });

    it('si el aviso falla la solicitud ya está guardada y se responde OK', async () => {
        notifyAccessRequest.mockResolvedValue(false);
        const result = await requestAccess(input);
        expect(result).toEqual({ ok: true, message: RECEIVED });
        expect(create).toHaveBeenCalled();
        expect(updateOne).not.toHaveBeenCalled();
    });

    it('email repetido: solo incrementa submissions, ni crea ni avisa de nuevo', async () => {
        findOne.mockResolvedValue({ _id: 'doc0' });
        const result = await requestAccess(input);
        expect(result).toEqual({ ok: true, message: RECEIVED });
        expect(updateOne).toHaveBeenCalledWith({ email: 'nico@example.com' }, { $inc: { submissions: 1 } });
        expect(create).not.toHaveBeenCalled();
        expect(notifyAccessRequest).not.toHaveBeenCalled();
    });

    it('5 solicitudes recientes desde la misma IP -> límite, no se guarda', async () => {
        countDocuments.mockResolvedValue(5);
        const result = await requestAccess(input);
        expect(result).toEqual({ ok: false, message: 'Demasiadas solicitudes desde tu conexión. Inténtalo más tarde.' });
        expect(countDocuments).toHaveBeenCalledWith({ ipHash: 'ip-hash-1', createdAt: { $gte: expect.any(Date) } });
        expect(create).not.toHaveBeenCalled();
    });

    it('carrera de duplicados (11000): la primera ya se guardó -> OK', async () => {
        create.mockRejectedValue(Object.assign(new Error('dup key'), { code: 11000 }));
        expect(await requestAccess(input)).toEqual({ ok: true, message: RECEIVED });
    });

    it('otro fallo de BD -> error genérico, sin detalle interno', async () => {
        connectToDatabase.mockRejectedValue(new Error('mongo topology closed: password=SECRET'));
        const result = await requestAccess(input);
        expect(result.ok).toBe(false);
        expect(result.message).toBe('No hemos podido guardar la solicitud ahora mismo. Inténtalo de nuevo en unos minutos.');
    });
});
