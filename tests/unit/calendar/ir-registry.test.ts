import { describe, expect, it } from 'vitest';

import { IR_REGISTRY, irLinksFor, type IrAssetKind } from '@/lib/ir-registry';

const ASSET_KINDS: readonly IrAssetKind[] = ['presentacion', 'webcast', 'directo', 'grabacion', 'transcripcion'];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

describe('IR_REGISTRY hygiene', () => {
    it('cada entrada tiene seccion https con etiqueta y fecha de verificacion ISO', () => {
        for (const [ticker, entry] of Object.entries(IR_REGISTRY)) {
            expect(ticker, ticker).toBe(ticker.toUpperCase());
            expect(entry.name.trim(), ticker).not.toBe('');
            expect(entry.section.url, ticker).toMatch(/^https:\/\//);
            expect(entry.section.label.trim(), ticker).not.toBe('');
            expect(entry.verifiedOn, ticker).toMatch(ISO_DATE);
        }
    });

    it('cada evento tiene fecha ISO, periodo, url https y assets https de tipo conocido', () => {
        for (const [ticker, entry] of Object.entries(IR_REGISTRY)) {
            for (const event of entry.events) {
                expect(event.date, `${ticker} ${event.url}`).toMatch(ISO_DATE);
                expect(event.period.trim(), `${ticker} ${event.url}`).not.toBe('');
                expect(event.url, `${ticker} ${event.date}`).toMatch(/^https:\/\//);
                for (const asset of event.assets ?? []) {
                    expect(ASSET_KINDS, `${ticker} ${asset.url}`).toContain(asset.kind);
                    expect(asset.url, `${ticker} ${asset.kind}`).toMatch(/^https:\/\//);
                    expect(asset.source, `${ticker} ${asset.kind}`).toMatch(/^https:\/\//);
                }
            }
        }
    });

    it('no hay dos eventos con la misma fecha en una entrada', () => {
        for (const [ticker, entry] of Object.entries(IR_REGISTRY)) {
            const dates = entry.events.map((e) => e.date);
            expect(new Set(dates).size, ticker).toBe(dates.length);
        }
    });
});

describe('irLinksFor', () => {
    it('devuelve null para tickers sin entrada', () => {
        expect(irLinksFor('NOEXISTE', '2026-11-08')).toBeNull();
    });

    it('normaliza el ticker a mayusculas', () => {
        expect(irLinksFor('meta', '2026-10-21')?.section.url).toBe(IR_REGISTRY.META.section.url);
    });

    it('solo enlaza la pagina del evento si la fecha coincide exactamente', () => {
        const exact = irLinksFor('META', '2026-10-21');
        expect(exact?.eventPage?.period).toBe('T3 2026');
        const otherDay = irLinksFor('META', '2026-10-22');
        expect(otherDay?.eventPage).toBeNull();
        expect(otherDay?.section.url).toBe(IR_REGISTRY.META.section.url);
    });

    it('una entrada sin eventos devuelve seccion y eventPage null', () => {
        const links = irLinksFor('TSLA', '2026-10-22');
        expect(links?.eventPage).toBeNull();
        expect(links?.section.url).toBe(IR_REGISTRY.TSLA.section.url);
    });

    it('los assets del evento llegan con su tipo', () => {
        const links = irLinksFor('BN', '2026-08-13');
        expect(links?.eventPage?.assets.map((a) => a.kind)).toEqual(['grabacion', 'transcripcion']);
    });
});
