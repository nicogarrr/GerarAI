import { beforeEach, expect, it } from 'vitest';
import type { Locator, Page } from '@playwright/test';
import { armDepartureScroll } from '../../../e2e/fixtures/departure-scroll';

let link: HTMLAnchorElement;
const page = { evaluate: async (fn: (key: string) => unknown, key: string) => fn(key) } as unknown as Page;
const locator = { evaluate: async (fn: (el: Element, key: string) => unknown, key: string) => fn(link, key) } as unknown as Locator;

beforeEach(() => {
    sessionStorage.clear();
    link = document.createElement('a');
    document.body.replaceChildren(link);
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 1613 });
});

it('samples on pointerdown only, rounds, survives navigation and consumes once', async () => {
    sessionStorage.setItem('e2e:departure-scroll', 'stale');
    const read = await armDepartureScroll(page, locator);
    expect(sessionStorage.getItem('e2e:departure-scroll')).toBeNull();
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 1645.4 });
    link.dispatchEvent(new PointerEvent('pointerdown'));
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 });
    link.dispatchEvent(new PointerEvent('pointerdown'));
    expect(await read()).toBe(1645);
    await expect(read()).rejects.toThrow('No pointerdown');
});

it('fails closed for missing or corrupt observations, but accepts zero', async () => {
    const read = await armDepartureScroll(page, locator);
    await expect(read()).rejects.toThrow('No pointerdown');
    sessionStorage.setItem('e2e:departure-scroll', 'broken');
    await expect(read()).rejects.toThrow('No pointerdown');
    sessionStorage.setItem('e2e:departure-scroll', '0');
    expect(await read()).toBe(0);
});
