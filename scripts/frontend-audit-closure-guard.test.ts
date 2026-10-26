/**
 * Cierre de auditoría frontend/UX/legal:
 *  1. consentimiento obligatorio en alta y solicitud de acceso;
 *  2. documentos legales en borrador: noindex, aviso visible y fuera del sitemap;
 *  3. secreto Base32 copiable en 2FA;
 *  4. recuperación de contraseña honesta según SMTP;
 *  5. 404 público sin enlaces al espacio privado;
 *  6. screener distingue «sin filtros guardados» de «motor caído»;
 *  7. copy de exportación coherente entre /privacidad y Seguridad;
 *  8. etiquetas ES de tipos de empresa e industrias del master.
 *
 * Ejecución: node --experimental-strip-types --test scripts/frontend-audit-closure-guard.test.ts
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { companyTypeLabel, sectorIndustryLine } from '../lib/labels.ts';

const read = (path: string) => readFileSync(path, 'utf8');

test('el alta exige aceptar Términos y Privacidad con enlaces', () => {
    const form = read('components/forms/SignUpForm.tsx');
    assert.match(form, /register\('acceptTerms'/);
    assert.ok(form.includes("required: 'Debes aceptar los Términos de uso"));
    assert.ok(form.includes('href="/terminos"'));
    assert.ok(form.includes('href="/privacidad"'));
    assert.ok(form.includes('errors.acceptTerms'));
});

test('la solicitud de acceso también exige aceptar los documentos', () => {
    const form = read('components/forms/AccessRequestForm.tsx');
    assert.ok(form.includes('ar-accept-terms'));
    assert.ok(form.includes('disabled={pending || !accepted}'));
    assert.ok(form.includes('href="/terminos"'));
    assert.ok(form.includes('href="/privacidad"'));
});

test('los documentos legales en borrador no se indexan ni se anuncian en el sitemap', () => {
    const privacy = read('app/(public)/privacidad/page.tsx');
    const terms = read('app/(public)/terminos/page.tsx');
    const sitemap = read('app/sitemap.ts');
    for (const page of [privacy, terms]) {
        assert.ok(page.includes('robots: { index: false, follow: false }'));
        assert.ok(page.includes('Aviso de borrador'));
    }
    assert.ok(!sitemap.includes('/privacidad'));
    assert.ok(!sitemap.includes('/terminos'));
});

test('2FA muestra el secreto Base32 copiable además del QR', () => {
    const settings = read('components/security/TwoFactorSettings.tsx');
    assert.ok(settings.includes("searchParams.get('secret')"));
    assert.ok(settings.includes('Clave manual (Base32)'));
    assert.ok(settings.includes('aria-label="Clave TOTP en Base32"'));
    assert.ok(settings.includes('Copiar clave'));
    assert.ok(settings.includes('role="img"'));
});

test('la recuperación de contraseña no promete correo si falta SMTP', () => {
    const page = read('app/(public)/forgot-password/page.tsx');
    const form = read('components/auth/ForgotPasswordForm.tsx');
    const signInForm = read('components/forms/SignInForm.tsx');
    const signInPage = read('app/(auth)/sign-in/page.tsx');
    assert.ok(page.includes('emailConfigured ?'));
    assert.ok(page.includes('no podemos'));
    assert.match(form, /no se enviará ningún\s+enlace/);
    assert.ok(form.includes('href="/help"'));
    assert.ok(signInForm.includes('passwordResetAvailable ?'));
    assert.ok(signInPage.includes('isPasswordResetEmailConfigured()'));
});

test('un titular externo sin traducir se etiqueta como original', () => {
    const headline = read('components/research/ExternalNewsHeadline.tsx');
    assert.ok(headline.includes('Titular original (sin traducir)'));
    assert.ok(headline.includes("translationState === 'original'"));
});

test('el 404 público no enlaza al espacio privado', () => {
    const notFound = read('app/not-found.tsx');
    for (const route of ['/inicio', '/discover', '/watchlist']) {
        assert.ok(!notFound.includes(`href="${route}"`), `404 no puede enlazar ${route}`);
    }
    assert.ok(notFound.includes('href="/"'));
    assert.ok(notFound.includes('href="/metodologia"'));
    assert.ok(notFound.includes('href="/help"'));
});

test('el screener distingue «sin filtros guardados» de «motor caído»', () => {
    const page = read('app/(root)/screener/page.tsx');
    assert.ok(!page.includes('Motor operativo pero sin filtros guardados'));
    assert.ok(!page.includes('Motor de análisis desconectado'));
    assert.ok(page.includes('Datos de mercado no disponibles'));
    assert.ok(page.includes('Índices no disponibles'));
    assert.ok(page.includes('Sin filtros guardados'));
    assert.ok(page.includes('El motor de análisis responde, pero no hay filtros guardados'));
    assert.ok(page.includes('motor de filtros no disponible'));
});

test('el copy de exportación dice qué incluye y qué no', () => {
    const settings = read('components/security/PrivacySettings.tsx');
    const privacy = read('app/(public)/privacidad/page.tsx');
    for (const source of [settings, privacy]) {
        assert.ok(source.includes('datos estructurados'));
        assert.ok(source.includes('originales de los documentos') || source.includes('archivos originales'));
    }
});

test('tipos de empresa e industrias del master tienen etiqueta ES', () => {
    assert.equal(companyTypeLabel('ai_big_tech'), 'big tech de IA');
    assert.equal(companyTypeLabel('uranium_mining'), 'minería de uranio');
    assert.equal(companyTypeLabel('software_ai_platform'), 'plataforma de software con IA');
    assert.equal(sectorIndustryLine('Technology', 'Software and cloud'), 'Tecnología · Software y nube');
    assert.equal(sectorIndustryLine('Technology', 'AI infrastructure'), 'Tecnología · Infraestructura de IA');
});
