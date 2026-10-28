/**
 * Guard de rendimiento: qrcode.react (~10 KB gz) no puede viajar en el bundle
 * inicial de /security. El QR solo se pinta al activar 2FA (tras enviar la
 * contraseña), así que carga con next/dynamic y se precarga al enviar el
 * formulario de activación. El contenedor accesible del QR (role="img") se
 * queda en el componente para no romper la jerarquía.
 *
 * Ejecución: node --experimental-strip-types --test scripts/two-factor-qr-lazy-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const settings = readFileSync('components/security/TwoFactorSettings.tsx', 'utf8');

describe('2FA: QR diferido fuera del bundle inicial', () => {
    it('qrcode.react no se importa en estático y carga con dynamic', () => {
        assert.ok(!/import\s+\{\s*QRCodeSVG\s*\}\s+from\s+'qrcode\.react'/.test(settings), 'sin import estático de qrcode.react');
        assert.match(settings, /dynamic\(loadQrCode/);
        assert.match(settings, /import\('qrcode\.react'\)\.then\(\(mod\) => mod\.QRCodeSVG\)/);
    });

    it('el fallback mantiene la caja de 160px para no mover el layout (CLS)', () => {
        assert.match(settings, /h-\[160px\] w-\[160px\]/);
        assert.match(settings, /role="img"/);
    });

    it('el chunk se precarga al enviar el formulario de activación', () => {
        assert.match(settings, /const handleEnable = async[\s\S]{0,200}void loadQrCode\(\);/);
    });
});
