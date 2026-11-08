// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';

/**
 * El metadataBase raíz fija el dominio absoluto de OG/Twitter/canonical de
 * TODA la app: debe ser el dominio real de producción (gerarai.duckdns.org,
 * front en la VM de Oracle detrás de Caddy), no el antiguo de Vercel.
 */
vi.mock('next/headers', () => ({
    cookies: async () => ({ get: () => undefined }),
    headers: async () => ({ get: () => null }),
}));
// generateMetadata no renderiza nada; los componentes del layout no importan
// para esta prueba y se sustituyen para no arrastrar la cadena cliente.
vi.mock('@/components/ui/sonner', () => ({ Toaster: () => null }));
vi.mock('@/components/pwa/ServiceWorkerRegister', () => ({ default: () => null }));
vi.mock('@/lib/i18n/client', () => ({ LocaleProvider: () => null }));
// El layout importa globals.css; PostCSS no está disponible en vitest.
vi.mock('@/app/globals.css', () => ({}));

import { generateMetadata } from '@/app/layout';

describe('metadata raíz', () => {
    it('metadataBase apunta al dominio de producción real, no al antiguo de Vercel', async () => {
        const md = await generateMetadata();
        expect(md.metadataBase?.toString()).toBe('https://gerarai.duckdns.org/');
    });

    it('el metadata no referencia el dominio vercel.app en ningún campo', async () => {
        const md = await generateMetadata();
        expect(JSON.stringify(md)).not.toContain('vercel.app');
    });
});
