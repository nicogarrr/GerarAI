import { describe, expect, it } from 'vitest';

import { IR_REGISTRY, irLinksFor, irLiveAssetFor, type IrAssetKind, type IrSectionLabelKey } from '@/lib/ir-registry';

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

describe('irLiveAssetFor', () => {
    it('fecha exacta con webcast: devuelve el asset y la fecha de verificación', () => {
        const live = irLiveAssetFor('meta', '2026-10-21');
        expect(live?.asset).toEqual(expect.objectContaining({ kind: 'webcast', url: 'https://events.q4inc.com/attendee/132342320' }));
        expect(live?.verifiedOn).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    });
    it('evento con webcast pero sin directo: devuelve el webcast', () => {
        expect(irLiveAssetFor('ASTS', '2026-11-09')?.asset.kind).toBe('webcast');
    });
    it('sin entrada, sin evento ese día o evento sin directo: null', () => {
        expect(irLiveAssetFor('ZZZZ', '2026-10-21')).toBeNull();
        expect(irLiveAssetFor('META', '2026-10-22')).toBeNull();
        expect(irLiveAssetFor('BN', '2026-11-13')).toBeNull();
    });
});

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

    it('cubre las posiciones y watchlist registradas el 2026-11-15', () => {
        // Guard anti-regresion: cada ticker registrado responde con su seccion oficial.
        for (const ticker of [
            'META', 'BN', 'TSLA', 'ASTS', 'ZETA', 'CGEO.L', 'KRKNF', 'BABA', 'BWMX', 'KKR', 'POOL', 'CB', 'CPT', 'UBER', 'RKLB', 'ONDS',
            'AMZN', 'SCHW', 'SPGI', 'GFL', 'REXR', 'JOE', 'CSL', 'BR', 'ALX', 'CNQ.TO', 'FFH.TO', 'AMRZ', 'FRPH', 'GCC.MX', 'WOSG.L',
            'MICC.AS', 'SFC.TO', 'ERF.PA', 'SKYH',
        ]) {
            expect(irLinksFor(ticker, '2026-11-15')?.section.url, ticker).toMatch(/^https:\/\//);
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
        ['UBER', '2026-11-04', 'investor.uber.com'],
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
        const links = irLinksFor('KRKNF', '2026-10-22');
        expect(links?.eventPage).toBeNull();
        expect(links?.section.url).toBe(IR_REGISTRY.KRKNF.section.url);
    });

    it('TSLA enlaza deck y webcast del T3 2026 solo ese dia', () => {
        const exact = irLinksFor('TSLA', '2026-10-21');
        expect(exact?.eventPage?.assets.map((a) => a.kind)).toEqual(['presentacion', 'webcast']);
        expect(irLiveAssetFor('TSLA', '2026-10-21')?.asset.url).toBe('https://ir.tesla.com/webcast-2026-10-21');
        expect(irLinksFor('TSLA', '2026-10-22')?.eventPage).toBeNull();
    });

    it('KKR enlaza la transcripcion del T3 2026 solo ese dia', () => {
        const exact = irLinksFor('KKR', '2026-11-09');
        expect(exact?.eventPage?.assets.map((a) => a.kind)).toEqual(['transcripcion']);
        expect(irLinksFor('KKR', '2026-11-10')?.eventPage).toBeNull();
    });

    it.each([
        ['AMZN', '2026-10-29', ['grabacion']],
        ['REXR', '2026-10-22', ['presentacion', 'webcast']],
        ['AMRZ', '2026-10-28', ['transcripcion']],
        ['FRPH', '2026-11-05', ['webcast', 'presentacion']],
        ['GCC.MX', '2026-10-27', ['presentacion', 'transcripcion']],
    ])('los materiales del T3 2026 de %s enlazan solo en su dia exacto', (ticker, date, kinds) => {
        const exact = irLinksFor(ticker, date);
        expect(exact?.eventPage?.period, ticker).toBe('T3 2026');
        expect(exact?.eventPage?.assets.map((a) => a.kind), ticker).toEqual(kinds);
        expect(irLinksFor(ticker, '2026-12-31')?.eventPage, ticker).toBeNull();
    });

    it.each([
        ['SCHW', '2026-10-15', 'aboutschwab.com'],
        ['SPGI', '2026-10-27', 'spglobal.com'],
        ['GFL', '2026-10-28', 'gflenv.com'],
        ['JOE', '2026-10-28', 'ir.joe.com'],
        ['CSL', '2026-10-28', 'carlisle.com'],
        ['BR', '2026-11-03', 'broadridge-ir.com'],
        ['ALX', '2026-11-02', 'alx-inc.com'],
        ['CNQ.TO', '2026-11-05', 'cnrl.com'],
        ['FFH.TO', '2026-11-03', 'fairfax.ca'],
        ['WOSG.L', '2026-11-10', 'thewosgroupplc.com'],
        ['MICC.AS', '2026-10-29', 'magnumicecream.com'],
        ['SFC.TO', '2026-11-11', 'sagicor.com'],
        ['ERF.PA', '2026-11-05', 'eurazeo.com'],
        ['CGEO.L', '2026-10-28', 'georgiacapital.ge'],
    ])('el evento de %s enlaza solo en su dia exacto', (ticker, date, host) => {
        const exact = irLinksFor(ticker, date);
        expect(exact?.eventPage?.url, ticker).toContain(host);
        expect(irLinksFor(ticker, '2026-12-31')?.eventPage, ticker).toBeNull();
    });

    it('los assets del evento llegan con su tipo', () => {
        const links = irLinksFor('BN', '2026-08-13');
        expect(links?.eventPage?.assets.map((a) => a.kind)).toEqual(['grabacion', 'transcripcion']);
    });

    it.each([
        ['MICC.AS', '2026-10-29', ['presentacion', 'webcast', 'transcripcion']],
        ['SFC.TO', '2026-11-11', ['presentacion', 'grabacion']],
        ['WOSG.L', '2026-11-10', ['webcast']],
        ['CGEO.L', '2026-10-28', ['presentacion']],
    ])('los materiales verificados el 2026-11-18 de %s enlazan solo en su dia exacto', (ticker, date, kinds) => {
        const exact = irLinksFor(ticker, date);
        expect(exact?.eventPage?.assets.map((a) => a.kind), ticker).toEqual(kinds);
        expect(irLinksFor(ticker, '2026-12-31')?.eventPage, ticker).toBeNull();
    });

    it('cubre las posiciones y watchlist registradas el 2026-11-18', () => {
        // Guard anti-regresion: NVDA y los 4X DCA sin entrada propia (CHTR, HIMS, NAUT, RXRX) + AMD.
        for (const ticker of ['NVDA', 'CHTR', 'HIMS', 'NAUT', 'RXRX', 'AMD']) {
            expect(irLinksFor(ticker, '2026-11-18')?.section.url, ticker).toMatch(/^https:\/\//);
        }
    });

    it('BN enlaza presentacion y webcast del T3 2026 solo ese dia', () => {
        const exact = irLinksFor('BN', '2026-11-12');
        expect(exact?.eventPage?.assets.map((a) => a.kind)).toEqual(['presentacion', 'webcast']);
        expect(irLiveAssetFor('BN', '2026-11-12')?.asset.url).toContain('edge.media-server.com');
        expect(irLinksFor('BN', '2026-11-13')?.eventPage).toBeNull();
    });

    it('cubre los 11 tickers BME de la watchlist con seccion IR oficial', () => {
        // Guard anti-regresion: BME anadidos a la watchlist el 2026-10-28.
        for (const ticker of ['SAN.MC', 'IBE.MC', 'AENA.MC', 'ENG.MC', 'RED.MC', 'GEST.MC', 'PRM.MC', 'VIS.MC', 'VID.MC', 'EBRO.MC', 'IBG.MC']) {
            expect(irLinksFor(ticker, '2026-11-18')?.section.url, ticker).toMatch(/^https:\/\//);
        }
    });

    it('ONDS enlaza presentacion y webcast del T3 2026 solo ese dia', () => {
        const exact = irLinksFor('ONDS', '2026-11-12');
        expect(exact?.eventPage?.assets.map((a) => a.kind)).toEqual(['presentacion', 'webcast']);
        expect(irLinksFor('ONDS', '2026-11-13')?.eventPage).toBeNull();
    });

    it('NVDA enlaza presentacion y webcast del T3 fiscal 2027 solo ese dia', () => {
        const exact = irLinksFor('NVDA', '2026-11-17');
        expect(exact?.eventPage?.period).toBe('T3 fiscal 2027');
        expect(exact?.eventPage?.assets.map((a) => a.kind)).toEqual(['presentacion', 'webcast']);
        expect(irLiveAssetFor('NVDA', '2026-11-17')?.asset.url).toContain('q4inc.com');
        expect(irLinksFor('NVDA', '2026-11-18')?.eventPage).toBeNull();
    });

    it('KRKNF lleva el webcast oficial anunciado para el 2026-11-24', () => {
        // Regresion 2026-11-18: posicion de cartera sin evento registrado para su T3 2026.
        const live = irLiveAssetFor('KRKNF', '2026-11-24');
        expect(live?.asset.kind).toBe('webcast');
        expect(live?.asset.url).toContain('choruscall.com');
        expect(irLiveAssetFor('KRKNF', '2026-11-25')).toBeNull();
    });

    it('SKYH enlaza su evento y webcast del T3 2026 solo ese dia', () => {
        const exact = irLinksFor('SKYH', '2026-11-10');
        expect(exact?.eventPage?.period).toBe('T3 2026');
        expect(exact?.eventPage?.assets.map((a) => a.kind)).toEqual(['webcast']);
        expect(irLinksFor('SKYH', '2026-11-11')?.eventPage).toBeNull();
    });

    it('BABA lleva el directo oficial anunciado para el 2026-11-19', () => {
        // Regresion 2026-11-18: el evento existia sin assets, asi que ni el chip
        // "Ver directo oficial" ni el aviso del dia llevaban el enlace.
        const live = irLiveAssetFor('BABA', '2026-11-19');
        expect(live?.asset.kind).toBe('webcast');
        expect(live?.asset.url).toBe('https://www.alibabagroup.com/en/ir/earnings');
        expect(irLiveAssetFor('BABA', '2026-11-20')).toBeNull();
    });
});
