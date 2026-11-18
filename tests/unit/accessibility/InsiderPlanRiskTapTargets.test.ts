/**
 * Auditoría móvil 18-nov-2026 (prod, viewport 390 px): objetivos táctiles por
 * debajo del suelo de la casa (32 px en listas densas, 44 px en controles).
 *
 * - /insider: 128 chips de ticker de PoliticianCard a 24 px y 10 enlaces de
 *   ticker de InsiderOperationsView a 24 px.
 * - /plan: enlaces de ticker de ContributionSplitCard a 16 px.
 * - /risk: enlaces de ticker de positionLink a 18 px y enlace inline
 *   «Inteligencia de cartera» a 16 px.
 * - /security: enlace «restablecer contraseña» a 16 px.
 *
 * Patrones de la casa: min-h-8 (32 px) en chips de listas densas con wrap, y
 * expansión de área con before:-inset-* en enlaces inline (no cambia el
 * layout, igual que en DcaLevelBadge y NewsSection).
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

function src(path: string): string {
    return readFileSync(join(ROOT, path), 'utf8');
}

describe('objetivos táctiles móviles: insider, plan, risk y security', () => {
    it('los chips de ticker de PoliticianCard llegan a 32 px (min-h-8)', () => {
        const s = src('components/research/PoliticianCard.tsx');
        expect(s).toContain('inline-flex min-h-8 items-center rounded border border-gray-800 px-2 py-0.5');
    });

    it('el ticker de InsiderOperationsView expande su área sin cambiar el layout', () => {
        const s = src('components/insider/InsiderOperationsView.tsx');
        const link = s.match(/<Link[\s\S]*?company\.ticker[\s\S]*?<\/Link>/)?.[0] ?? '';
        expect(link).toContain('before:absolute');
        expect(link).toContain('before:-inset-y-2');
        expect(link).toContain('relative');
    });

    it('los tickers de ContributionSplitCard expanden su área a 32 px', () => {
        const s = src('components/plan/ContributionSplitCard.tsx');
        const link = s.match(/<Link[\s\S]*?row\.ticker[\s\S]*?<\/Link>/)?.[0] ?? '';
        expect(link).toContain('before:absolute');
        expect(link).toContain('before:-inset-y-2');
    });

    it('los tickers de risk (positionLink) expanden su área', () => {
        const s = src('components/risk/RiskDashboardView.tsx');
        const fn = s.match(/function positionLink[\s\S]*?\n}/)?.[0] ?? '';
        expect(fn).toContain('before:absolute');
        expect(fn).toContain('before:-inset-y-2');
    });

    it('el enlace inline a Inteligencia de cartera en /risk expande su área', () => {
        const s = src('app/(root)/risk/page.tsx');
        const link = s.match(/<Link[^>]*portfolio\/intelligence[^>]*>/)?.[0] ?? '';
        expect(link).toContain('before:absolute');
        expect(link).toContain('before:-inset-y-2');
    });

    it('el enlace «restablecer contraseña» de /security expande su área', () => {
        const s = src('app/(root)/security/page.tsx');
        const link = s.match(/<Link[^>]*forgot-password[^>]*>/)?.[0] ?? '';
        expect(link).toContain('before:absolute');
        expect(link).toContain('before:-inset-y-2');
    });
});
