import { describe, expect, it } from 'vitest';

import { IR_REGISTRY, irLinksFor, type IrAssetKind, type IrSectionLabelKey } from '@/lib/ir-registry';

const ASSET_KINDS: readonly IrAssetKind[] = ['presentacion', 'webcast', 'directo', 'grabacion', 'transcripcion'];
const SECTION_LABEL_KEYS: readonly IrSectionLabelKey[] = [
    'investorEvents',
    'quarterlyResults',
    'documentsAndEvents',
    'eventsAndPresentations',
    'resultsAndReports',
    'pressReleases',
    'investorRelations',
];
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

describe('IR_REGISTRY hygiene', () => {
    it('cada entrada tiene seccion https con etiqueta y fecha de verificacion ISO', () => {
        for (const [ticker, entry] of Object.entries(IR_REGISTRY)) {
            expect(ticker, ticker).toBe(ticker.toUpperCase());
            expect(entry.name.trim(), ticker).not.toBe('');
            expect(entry.section.url, ticker).toMatch(/^https:\/\//);
            expect(SECTION_LABEL_KEYS, ticker).toContain(entry.section.labelKey);
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

    it('cubre las posiciones y watchlist registradas el 2026-11-09', () => {
        // Guard anti-regresion: cada ticker registrado responde con su seccion oficial.
        for (const ticker of ['META', 'BN', 'TSLA', 'ASTS', 'ZETA', 'CGEO.L', 'KRKNF', 'BABA', 'BWMX', 'KKR', 'POOL', 'CB', 'CPT', 'UBER', 'RKLB', 'ONDS']) {
            expect(irLinksFor(ticker, '2026-11-08')?.section.url, ticker).toMatch(/^https:\/\//);
        }
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

    it('enlaza el evento RKLB del 2026-11-09 solo ese dia', () => {
        const exact = irLinksFor('RKLB', '2026-11-09');
        expect(exact?.eventPage?.period).toBe('T3 2026');
        expect(irLinksFor('RKLB', '2026-11-10')?.eventPage).toBeNull();
    });

    it('enlaza el evento ONDS del 2026-11-12 solo ese dia', () => {
        const exact = irLinksFor('ONDS', '2026-11-12');
        expect(exact?.eventPage?.url).toContain('ir.ondas.com/ir-calendar/');
        expect(irLinksFor('ONDS', '2026-11-11')?.eventPage).toBeNull();
    });

    it.each([
        ['ZETA', '2026-11-09', 'zetaglobal.com'],
        ['BWMX', '2026-10-22', 'befra.com'],
        ['POOL', '2026-10-22', 'poolcorp.com'],
        ['CB', '2026-10-20', 'investors.chubb.com'],
        ['CPT', '2026-11-05', 'camdenliving.com'],
        ['BABA', '2026-11-19', 'alibabagroup.com'],
    ])('el evento T3 2026 de %s enlaza solo en su dia exacto', (ticker, date, host) => {
        const exact = irLinksFor(ticker, date);
        expect(exact?.eventPage?.period).toBe('T3 2026');
        expect(exact?.eventPage?.url).toContain(host);
        expect(irLinksFor(ticker, '2026-12-31')?.eventPage).toBeNull();
    });

    it('el evento ASTS del 2026-11-09 enlaza su webcast solo ese dia', () => {
        const exact = irLinksFor('ASTS', '2026-11-09');
        expect(exact?.eventPage?.period).toBe('T3 2026');
        expect(exact?.eventPage?.assets.map((a) => a.kind)).toEqual(['webcast']);
        expect(irLinksFor('ASTS', '2026-11-10')?.eventPage).toBeNull();
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
