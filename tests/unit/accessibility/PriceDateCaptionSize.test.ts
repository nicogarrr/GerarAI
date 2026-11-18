import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Fecha/fuente del precio legible (auditoría móvil 18-nov-2026 sobre prod,
// viewport 390x844): los pies «Cierre {date}» / «Dato diario del {date}» de
// /inicio (PersonalizedOverview), /watchlist y /screener se pintaban a 10 px.
// Son datos de veracidad (qué fecha tiene el precio), no decoración, y el
// suelo del producto para texto de lectura es text-xs (12 px) desde la
// auditoría de contraste del 11-nov (readable-grey-text-contrast).
// Medido en prod: 3 en /inicio, 17 en /watchlist, 14 en /screener a 10 px.
// El sup «*» de market cap derivado se queda a 10 px: es un marcador
// tipográfico, no una frase de lectura.

const src = (p: string) => readFileSync(p, 'utf8');

describe('pie de fecha del precio a 12 px (text-xs), no 10 px', () => {
    it('watchlist: «Cierre el {date}» de cada ficha', () => {
        const s = src('app/(root)/watchlist/page.tsx');
        expect(s).toContain("text-xs font-normal text-gray-500\">{stock.priceAsOf ? t('watchlist.page.closeOn'");
        expect(s).not.toContain("text-[10px] font-normal text-gray-500\">{stock.priceAsOf ? t('watchlist.page.closeOn'");
    });

    it('screener: divisa ausente, dato diario y vela observada', () => {
        const s = src('app/(root)/screener/page.tsx');
        expect(s).toContain("text-xs text-gray-500\">{t('screener.currencyMissing')}");
        expect(s).toContain("text-xs text-gray-500\">{r.priceDate ? t('screener.dailyData'");
        expect(s).toContain("text-right text-xs text-gray-500\">{quoteObserved(i.priceAsOf, 'daily_candle_open', locale)}");
        expect(s).not.toContain('text-right text-[10px] text-gray-500');
    });

    it('inicio: «Cierre {date}» y «Sin datos» de la watchlist del resumen', () => {
        const s = src('components/PersonalizedOverview.tsx');
        expect(s).toContain("text-xs text-gray-500\">{stock.priceAsOf ? t('home.watchlist.close'");
        expect(s).toContain("text-xs uppercase tracking-wide text-gray-500\">{t('home.watchlist.noData')}");
        expect(s).not.toContain("text-[10px] uppercase tracking-wide text-gray-500\">{t('home.watchlist.noData')}");
    });
});
