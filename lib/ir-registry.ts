/**
 * Registro de enlaces oficiales de relacion con inversores (IR), verificado a mano contra la web
 * publica de cada empresa. Solo enlaces, nunca contenido copiado.
 *
 * - `events`: pagina concreta de un evento de resultados, con su fecha. Solo se muestra si la
 *   fecha del evento del calendario coincide EXACTAMENTE; si no coincide no se enlaza (se
 *   conserva la discrepancia en vez de adivinar).
 * - `section`: pagina oficial de eventos/resultados del emisor (enlace general, no de un evento).
 * - `verifiedOn`: dia en que se abrio y se comprobo la URL. Frescura visible en el tooltip.
 * Cobertura: solo los emisores listados; el resto no muestra enlace IR (ausencia, no "no disponible").
 * Los enlaces de directo, grabacion y transcripcion viven en esas paginas cuando la empresa los
 * publica; este registro no los extrae ni los promete.
 */

/** Tipo de material enlazado. Cuatro cosas distintas: no se mezclan ni se infieren unas de otras. */
export type IrAssetKind = 'presentacion' | 'webcast' | 'directo' | 'grabacion' | 'transcripcion';
/** Enlace directo verificado a un archivo del evento; `source` es la pagina oficial donde se anuncia. */
export type IrAsset = { kind: IrAssetKind; url: string; source: string };
/** Clave i18n de la etiqueta de la seccion (calendar.earnings.irLabels.*): el texto vive en lib/i18n/messages. */
export type IrSectionLabelKey =
    | 'investorEvents'
    | 'quarterlyResults'
    | 'documentsAndEvents'
    | 'eventsAndPresentations'
    | 'resultsAndReports'
    | 'pressReleases'
    | 'investorRelations';
export type IrEventPage = { date: string; period: string; url: string; assets?: IrAsset[] };
export type IrEntry = {
    name: string;
    section: { url: string; labelKey: IrSectionLabelKey };
    events: IrEventPage[];
    verifiedOn: string;
};

export const IR_REGISTRY: Record<string, IrEntry> = {
    META: {
        name: 'Meta Platforms',
        section: { url: 'https://investor.atmeta.com/investor-events/', labelKey: 'investorEvents' },
        events: [
            {
                date: '2026-10-21',
                period: 'T3 2026',
                url: 'https://investor.atmeta.com/investor-events/event-details/2026/Q3-2026-Earnings-Call/default.aspx',
                assets: [
                    { kind: 'webcast', url: 'https://events.q4inc.com/attendee/132342320', source: 'https://investor.atmeta.com/investor-events/event-details/2026/Q3-2026-Earnings-Call/default.aspx' },
                    { kind: 'presentacion', url: 'https://s21.q4cdn.com/399680738/files/content_files/Earnings-Presentation-Q3-2026.pdf', source: 'https://investor.atmeta.com/investor-events/event-details/2026/Q3-2026-Earnings-Call/default.aspx' },
                ],
            },
            { date: '2026-07-29', period: 'T2 2026', url: 'https://investor.atmeta.com/investor-events/event-details/2026/Q2-2026-Earnings-Call/default.aspx' },
            {
                date: '2026-04-29',
                period: 'T1 2026',
                url: 'https://investor.atmeta.com/investor-events/event-details/2026/Q1-2026-Earnings-Call/default.aspx',
                assets: [
                    { kind: 'presentacion', url: 'https://s21.q4cdn.com/399680738/files/doc_financials/2026/q1/Earnings-Presentation-Q1-2026.pdf', source: 'https://investor.atmeta.com/investor-events/event-details/2026/Q1-2026-Earnings-Call/default.aspx' },
                    { kind: 'transcripcion', url: 'https://s21.q4cdn.com/399680738/files/doc_financials/2026/q1/META-Q1-2026-Earnings-Call-Transcript.pdf', source: 'https://investor.atmeta.com/investor-events/event-details/2026/Q1-2026-Earnings-Call/default.aspx' },
                ],
            },
        ],
        verifiedOn: '2026-10-21',
    },
    BN: {
        name: 'Brookfield Corporation',
        section: { url: 'https://bn.brookfield.com/reports-filings/quarterly-results', labelKey: 'quarterlyResults' },
        events: [
            { date: '2026-11-12', period: 'T3 2026', url: 'https://bn.brookfield.com/events/bn-q3-2026-conference-call-webcast' },
            {
                date: '2026-08-13',
                period: 'T2 2026',
                url: 'https://bn.brookfield.com/events/bn-q2-2026-conference-call-webcast',
                assets: [
                    { kind: 'grabacion', url: 'https://bn.brookfield.com/sites/brookfield-bn-v2/files/Brookfield-BN-IR-V2/2026/Q2/brookfield-corporation-2026-q2-conference-call-and-webcast.mp3', source: 'https://bn.brookfield.com/events/bn-q2-2026-conference-call-webcast' },
                    { kind: 'transcripcion', url: 'https://bn.brookfield.com/sites/brookfield-bn-v2/files/Brookfield-BN-IR-V2/2026/Q2/BN%20Q2-2026-transcript.pdf', source: 'https://bn.brookfield.com/events/bn-q2-2026-conference-call-webcast' },
                ],
            },
        ],
        verifiedOn: '2026-10-21',
    },
    TSLA: {
        name: 'Tesla',
        section: { url: 'https://ir.tesla.com/', labelKey: 'documentsAndEvents' },
        events: [],
        verifiedOn: '2026-10-21',
    },
    ASTS: {
        name: 'AST SpaceMobile',
        section: { url: 'https://investors.ast-science.com/', labelKey: 'quarterlyResults' },
        events: [
            // La web de ASTS no tiene pagina por evento: se enlaza la pagina oficial
            // de eventos, donde figura la convocatoria con su fecha y su webcast.
            {
                date: '2026-11-09',
                period: 'T3 2026',
                url: 'https://investors.ast-science.com/events',
                assets: [
                    { kind: 'webcast', url: 'https://event.choruscall.com/mediaframe/webcast.html?webcastid=QKToBNQI', source: 'https://investors.ast-science.com/events' },
                ],
            },
            {
                date: '2026-08-10',
                period: 'T2 2026',
                url: 'https://investors.ast-science.com/events',
                assets: [
                    { kind: 'webcast', url: 'https://event.choruscall.com/mediaframe/webcast.html?webcastid=LzBpQrob', source: 'https://investors.ast-science.com/events' },
                    { kind: 'presentacion', url: 'https://irp.cdn-website.com/bbb776b9/files/uploaded/AST+SpaceMobile+Q2+2026+Business+Update_vF.pdf', source: 'https://investors.ast-science.com/events' },
                ],
            },
        ],
        verifiedOn: '2026-11-09',
    },
    ZETA: {
        name: 'Zeta Global',
        section: { url: 'https://investors.zetaglobal.com/events-and-presentations/default.aspx', labelKey: 'eventsAndPresentations' },
        events: [
            { date: '2026-11-09', period: 'T3 2026', url: 'https://www.investors.zetaglobal.com/events-and-presentations/event-details/2026/Zeta-Q3-2026-Earnings-Call-2026-bhoMhuFrO0/default.aspx' },
        ],
        verifiedOn: '2026-11-09',
    },
    'CGEO.L': {
        name: 'Georgia Capital',
        section: { url: 'https://georgiacapital.ge/investor-relations/financial-results', labelKey: 'resultsAndReports' },
        events: [],
        verifiedOn: '2026-11-08',
    },
    KRKNF: {
        name: 'Kraken Robotics',
        section: { url: 'https://krakenrobotics.com/investors/press-releases/', labelKey: 'pressReleases' },
        events: [],
        verifiedOn: '2026-11-08',
    },
    BABA: {
        name: 'Alibaba Group',
        section: { url: 'https://www.alibabagroup.com/en-US/ir-financial-reports-quarterly-results', labelKey: 'quarterlyResults' },
        events: [
            // Anuncio oficial de la fecha (19 nov 2026, trimestre de septiembre).
            { date: '2026-11-19', period: 'T3 2026', url: 'https://home.alibabagroup.com/en-US/document-2054756418245885952' },
        ],
        verifiedOn: '2026-11-09',
    },
    BWMX: {
        name: 'Betterware de México',
        section: { url: 'https://www.befra.com/financials/quarterly-results', labelKey: 'quarterlyResults' },
        events: [
            { date: '2026-10-22', period: 'T3 2026', url: 'https://www.befra.com/news-events/press-releases/detail/108/befra-reports-third-quarter-2026-results' },
        ],
        verifiedOn: '2026-11-09',
    },
    KKR: {
        name: 'KKR & Co.',
        section: { url: 'https://ir.kkr.com/', labelKey: 'eventsAndPresentations' },
        events: [],
        verifiedOn: '2026-11-08',
    },
    POOL: {
        name: 'Pool Corporation',
        section: { url: 'https://ir.poolcorp.com/', labelKey: 'investorRelations' },
        events: [
            { date: '2026-10-22', period: 'T3 2026', url: 'https://ir.poolcorp.com/pool-corporation-reports-third-quarter-results-confirms-annual-earnings-guidance-range/' },
        ],
        verifiedOn: '2026-11-09',
    },
    CB: {
        name: 'Chubb',
        section: { url: 'https://investors.chubb.com/', labelKey: 'investorRelations' },
        events: [
            // Resultados publicados el 2026-10-20 (nota oficial); la llamada fue el 21.
            { date: '2026-10-20', period: 'T3 2026', url: 'https://investors.chubb.com/News--Events/news/news-details/2026/Chubb-Reports-Third-Quarter-Per-Share-Net-Income-and-Record-Core-Operating-Income-of-7-30-and-7-66-Respectively-Up-4-4-and-0-8-Consolidated-Net-Premiums-Written-of-15-1-Billion-Up-1-9-with-PC-and-Life-Insurance-Up-1-9-and-1-4-PC-Combined-Ratio-of-84-/default.aspx' },
        ],
        verifiedOn: '2026-11-09',
    },
    CPT: {
        name: 'Camden Property Trust',
        section: { url: 'https://investors.camdenliving.com/', labelKey: 'investorRelations' },
        events: [
            { date: '2026-11-05', period: 'T3 2026', url: 'https://investors.camdenliving.com/investors/news-events-presentations/news/news-details/2026/Camden-Property-Trust-Announces-Third-Quarter-2026-Operating-Results/default.aspx' },
        ],
        verifiedOn: '2026-11-09',
    },
    UBER: {
        name: 'Uber Technologies',
        section: { url: 'https://investor.uber.com/news-events/', labelKey: 'eventsAndPresentations' },
        events: [],
        verifiedOn: '2026-11-09',
    },
    RKLB: {
        name: 'Rocket Lab',
        section: { url: 'https://investors.rocketlabcorp.com/events-presentations/events', labelKey: 'eventsAndPresentations' },
        events: [
            { date: '2026-11-09', period: 'T3 2026', url: 'https://investors.rocketlabcorp.com/events/event-details/third-quarter-2026-financial-results-update-and-conference-call' },
        ],
        verifiedOn: '2026-11-09',
    },
    ONDS: {
        name: 'Ondas',
        section: { url: 'https://ir.ondas.com/financial-results', labelKey: 'quarterlyResults' },
        events: [
            { date: '2026-11-12', period: 'T3 2026', url: 'https://ir.ondas.com/ir-calendar/detail/4846/third-quarter-2026-earnings-conference-call' },
        ],
        verifiedOn: '2026-11-09',
    },
};

export type IrLinks = {
    eventPage: { url: string; period: string; assets: IrAsset[] } | null;
    section: { url: string; labelKey: IrSectionLabelKey };
    verifiedOn: string;
};

export function irLinksFor(ticker: string, eventDate: string): IrLinks | null {
    const entry = IR_REGISTRY[ticker.toUpperCase()];
    if (!entry) return null;
    const page = entry.events.find((e) => e.date === eventDate);
    return {
        eventPage: page ? { url: page.url, period: page.period, assets: page.assets ?? [] } : null,
        section: entry.section,
        verifiedOn: entry.verifiedOn,
    };
}
