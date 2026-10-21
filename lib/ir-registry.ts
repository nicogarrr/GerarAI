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
export type IrEventPage = { date: string; period: string; url: string; assets?: IrAsset[] };
export type IrEntry = {
    name: string;
    section: { url: string; label: string };
    events: IrEventPage[];
    verifiedOn: string;
};

export const IR_REGISTRY: Record<string, IrEntry> = {
    META: {
        name: 'Meta Platforms',
        section: { url: 'https://investor.atmeta.com/investor-events/', label: 'Eventos de inversores' },
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
        section: { url: 'https://bn.brookfield.com/reports-filings/quarterly-results', label: 'Resultados trimestrales' },
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
        section: { url: 'https://ir.tesla.com/', label: 'Documentos y eventos' },
        events: [],
        verifiedOn: '2026-10-21',
    },
    ASTS: {
        name: 'AST SpaceMobile',
        section: { url: 'https://investors.ast-science.com/', label: 'Resultados trimestrales' },
        events: [],
        verifiedOn: '2026-10-21',
    },
};

export type IrLinks = {
    eventPage: { url: string; period: string; assets: IrAsset[] } | null;
    section: { url: string; label: string };
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
