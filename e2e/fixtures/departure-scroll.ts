import type { Locator, Page } from '@playwright/test';

/** Independent oracle: sample the user's actual departure, not a coordinate
 * from before click actionability, native anchoring or a late layout shift.
 * sessionStorage survives both SPA navigation and a full same-origin load.
 * This key is test-only and never reads the product's scroll memory. */
export async function armDepartureScroll(page: Page, link: Locator) {
    const key = 'e2e:departure-scroll';
    await link.evaluate((element, storageKey) => {
        sessionStorage.removeItem(storageKey);
        element.addEventListener('pointerdown', () => {
            sessionStorage.setItem(storageKey, String(Math.round(window.scrollY)));
        }, { capture: true, once: true });
    }, key);
    return async () => page.evaluate((storageKey) => {
        const value = sessionStorage.getItem(storageKey);
        sessionStorage.removeItem(storageKey);
        if (value === null || !Number.isFinite(Number(value))) {
            throw new Error('No pointerdown departure scroll was recorded');
        }
        return Number(value);
    }, key);
}
