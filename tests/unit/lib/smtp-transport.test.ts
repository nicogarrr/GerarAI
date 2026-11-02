import { expect, it, vi } from 'vitest';
const create = vi.hoisted(() => vi.fn());
vi.mock('nodemailer', () => ({ default: { createTransport:create } }));
import { createSmtpTransport } from '@/lib/smtp-transport';
it('keeps credentials timeouts and TLS policy identical without sending mail', () => {
    for (const port of [465,587]) {
        createSmtpTransport({ host:'smtp.example.invalid',port,user:'test',pass:'placeholder',from:'test@example.invalid' });
        expect(create).toHaveBeenLastCalledWith({ host:'smtp.example.invalid',port,secure:port===465,auth:{ user:'test',pass:'placeholder' },connectionTimeout:8000,greetingTimeout:8000,socketTimeout:10000 });
    }
});
