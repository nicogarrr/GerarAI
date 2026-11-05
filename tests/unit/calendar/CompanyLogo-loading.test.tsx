import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { render, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';

afterEach(cleanup);

describe('decorative company logos do not hold document load', () => {
    it('SSR does not emit eager FMP image preloads for a company list', () => {
        const html = renderToStaticMarkup(createElement('div', null,
            ...['AAPL', 'ASML', 'BKR', 'AMZN'].map(ticker =>
                createElement(CompanyLogo, { ticker, name: ticker, key: ticker })),
        ));
        expect(html).not.toMatch(/<link[^>]*rel="preload"[^>]*as="image"/);
        expect(html.match(/loading="lazy"/g)).toHaveLength(4);
        expect(html.match(/decoding="async"/g)).toHaveLength(4);
        expect(html).toContain('https://financialmodelingprep.com/image-stock/AAPL.png');
    });

    it('keeps the same source, decorative alt and avatar while the logo loads', () => {
        const { container } = render(createElement(CompanyLogo, { ticker: 'AAPL', name: 'Apple', className: 'size-10' }));
        const image = container.querySelector('img');
        expect(image?.getAttribute('src')).toBe('https://financialmodelingprep.com/image-stock/AAPL.png');
        expect(image?.getAttribute('alt')).toBe('');
        expect(image?.getAttribute('loading')).toBe('lazy');
        expect(image?.getAttribute('crossorigin')).toBe('anonymous');
        expect(image?.getAttribute('referrerpolicy')).toBe('no-referrer');
        expect(container.textContent).toContain('A');
    });
});
