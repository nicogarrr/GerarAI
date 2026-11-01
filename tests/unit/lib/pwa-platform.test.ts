import { afterEach, describe, expect, it, vi } from 'vitest';

import { isIos, isStandalone } from '@/lib/pwa/platform';

/** UA real de cada plataforma (tal cual los expone el navegador). */
const IPHONE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1';
const IPADOS_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15';
const ANDROID_UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';
const MAC_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

function stubPlatform(ua: string, maxTouchPoints: number) {
    vi.stubGlobal('navigator', { userAgent: ua, maxTouchPoints });
}

function stubMatchMedia(standalone: boolean) {
    vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
        matches: query === '(display-mode: standalone)' && standalone,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
    })));
}

afterEach(() => vi.unstubAllGlobals());

describe('isIos', () => {
    it('detecta iPhone por el user agent', () => {
        stubPlatform(IPHONE_UA, 5);
        expect(isIos()).toBe(true);
    });

    it('detecta iPadOS aunque se presente como Macintosh (pantalla táctil)', () => {
        stubPlatform(IPADOS_UA, 5);
        expect(isIos()).toBe(true);
    });

    it('un Mac de escritorio sin táctil NO es iOS', () => {
        stubPlatform(MAC_UA, 0);
        expect(isIos()).toBe(false);
    });

    it('Android NO es iOS', () => {
        stubPlatform(ANDROID_UA, 5);
        expect(isIos()).toBe(false);
    });
});

describe('isStandalone', () => {
    it('true con display-mode standalone (Android/desktop instalado)', () => {
        stubPlatform(ANDROID_UA, 5);
        stubMatchMedia(true);
        expect(isStandalone()).toBe(true);
    });

    it('true con el flag navigator.standalone de Safari iOS aunque matchMedia diga que no', () => {
        vi.stubGlobal('navigator', { userAgent: IPHONE_UA, maxTouchPoints: 5, standalone: true });
        stubMatchMedia(false);
        expect(isStandalone()).toBe(true);
    });

    it('false en navegador normal (sin standalone ni flag)', () => {
        stubPlatform(MAC_UA, 0);
        stubMatchMedia(false);
        expect(isStandalone()).toBe(false);
    });
});
