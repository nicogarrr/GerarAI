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
            {
                date: '2026-11-12',
                period: 'T3 2026',
                url: 'https://bn.brookfield.com/events/bn-q3-2026-conference-call-webcast',
                assets: [
                    { kind: 'presentacion', url: 'https://bn.brookfield.com/sites/brookfield-bn-v2/files/Brookfield-BN-IR-V2/2026/Q3/2026-q3-bn-supplemental.pdf', source: 'https://bn.brookfield.com/events/bn-q3-2026-conference-call-webcast' },
                ],
            },
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
        events: [
            // Tesla no tiene pagina por evento: la tabla de ir.tesla.com enlaza deck y webcast del trimestre.
            {
                date: '2026-10-21',
                period: 'T3 2026',
                url: 'https://ir.tesla.com/',
                assets: [
                    { kind: 'presentacion', url: 'https://assets-ir.tesla.com/tesla-contents/IR/TSLA-Q3-2026-Update.pdf', source: 'https://ir.tesla.com/' },
                    { kind: 'webcast', url: 'https://ir.tesla.com/webcast-2026-10-21', source: 'https://ir.tesla.com/' },
                ],
            },
        ],
        verifiedOn: '2026-11-15',
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
        events: [
            { date: '2026-10-28', period: 'T3 2026', url: 'https://georgiacapital.ge/news/company-news/1324-georgia-capital-plc-3q26-and-9m26-results' },
        ],
        verifiedOn: '2026-11-15',
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
        events: [
            {
                date: '2026-11-09',
                period: 'T3 2026',
                url: 'https://ir.kkr.com/media/document/39297093-8255-4c8f-aae0-597950d1d2e8/assets/KKR_Q326_Earnings_Release.pdf?disposition=inline',
                assets: [
                    { kind: 'transcripcion', url: 'https://ir.kkr.com/media/document/a67ddf30-f2ff-44ff-be19-b57a090a95bb/assets/KKR_Q326_Earnings_Transcript.pdf?disposition=inline', source: 'https://ir.kkr.com/events-presentations' },
                ],
            },
        ],
        verifiedOn: '2026-11-15',
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
        events: [
            { date: '2026-11-04', period: 'T3 2026', url: 'https://investor.uber.com/news-events/news/press-release-details/2026/Uber-Announces-Results-for-Third-Quarter-2026/default.aspx' },
        ],
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
    AMZN: {
        name: 'Amazon.com',
        section: { url: 'https://ir.aboutamazon.com/quarterly-results/default.aspx', labelKey: 'quarterlyResults' },
        events: [
            {
                date: '2026-10-29',
                period: 'T3 2026',
                url: 'https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Third-Quarter-Results/default.aspx',
                assets: [
                    { kind: 'grabacion', url: 'https://ir.aboutamazon.com/files/doc_earnings/2026/q3/Q3-2026-Amazon-Earnings-Conference-Call.mp3', source: 'https://ir.aboutamazon.com/events/event-details/2026/Q3-2026-Amazoncom-Inc-Earnings-Conference-Call/default.aspx' },
                ],
            },
        ],
        verifiedOn: '2026-11-15',
    },
    SCHW: {
        name: 'Charles Schwab',
        section: { url: 'https://www.aboutschwab.com/investor-relations', labelKey: 'investorRelations' },
        events: [
            { date: '2026-10-15', period: 'T3 2026', url: 'https://pressroom.aboutschwab.com/press-releases/press-release/2026/Schwab-Delivers-Record-Net-New-Assets--Earnings/default.aspx' },
        ],
        verifiedOn: '2026-11-15',
    },
    SPGI: {
        name: 'S&P Global',
        section: { url: 'https://investor.spglobal.com/', labelKey: 'investorRelations' },
        events: [
            { date: '2026-10-27', period: 'T3 2026', url: 'https://investor.spglobal.com/news-releases/news-details/2026/SP-Global-Reports-Third-Quarter-Results-Announces-Strategic-Review-for-Capital-IQ-and-Associated-Data-Businesses/default.aspx' },
        ],
        verifiedOn: '2026-11-15',
    },
    GFL: {
        name: 'GFL Environmental',
        section: { url: 'https://investors.gflenv.com/', labelKey: 'investorRelations' },
        events: [
            { date: '2026-10-28', period: 'T3 2026', url: 'https://investors.gflenv.com/English/news/news-details/2026/GFL-Environmental-Reports-Third-Quarter-2026-Results-and-Raises-Full-Year-2026-Guidance/default.aspx' },
        ],
        verifiedOn: '2026-11-15',
    },
    REXR: {
        name: 'Rexford Industrial',
        section: { url: 'https://ir.rexfordindustrial.com/', labelKey: 'investorRelations' },
        events: [
            {
                date: '2026-10-22',
                period: 'T3 2026',
                url: 'https://ir.rexfordindustrial.com/news-events/press-releases/detail/381/rexford-industrial-announces-third-quarter-2026-financial-results',
                assets: [
                    { kind: 'presentacion', url: 'https://d1io3yog0oux5.cloudfront.net/_aedb72fc8626441a86045b167edcc762/rexfordindustrial/db/944/9733/earnings_presentation/Earnings+Deck+Q3+2026+vF.pdf', source: 'https://ir.rexfordindustrial.com/news-events/events-webcasts/detail/20261023-third-quarter-2026-earnings-conference-call' },
                    { kind: 'webcast', url: 'https://events.q4inc.com/attendee/238759897/guest', source: 'https://ir.rexfordindustrial.com/news-events/events-webcasts/detail/20261023-third-quarter-2026-earnings-conference-call' },
                ],
            },
        ],
        verifiedOn: '2026-11-15',
    },
    JOE: {
        name: 'St. Joe',
        section: { url: 'https://www.joe.com/investor-relations', labelKey: 'investorRelations' },
        events: [
            { date: '2026-10-28', period: 'T3 2026', url: 'https://ir.joe.com/news-releases/news-release-details/st-joe-company-reports-third-quarter-and-first-nine-months-2026/' },
        ],
        verifiedOn: '2026-11-15',
    },
    CSL: {
        name: 'Carlisle',
        section: { url: 'https://www.carlisle.com/investors', labelKey: 'investorRelations' },
        events: [
            { date: '2026-10-28', period: 'T3 2026', url: 'https://www.carlisle.com/investors/news/press-release-details/2026/Carlisle-Companies-Reports-Third-Quarter-Results/default.aspx' },
        ],
        verifiedOn: '2026-11-15',
    },
    BR: {
        name: 'Broadridge',
        section: { url: 'https://www.broadridge-ir.com/', labelKey: 'investorRelations' },
        events: [
            // Broadridge cierra su ejercicio fiscal en junio: es el T1 del ejercicio 2027.
            { date: '2026-11-03', period: 'T1 fiscal 2027', url: 'https://www.broadridge-ir.com/news/news-details/2026/Broadridge-Reports-First-Quarter-Fiscal-2027-Results/default.aspx' },
        ],
        verifiedOn: '2026-11-15',
    },
    ALX: {
        name: "Alexander's",
        section: { url: 'https://alx-inc.com/press-release/', labelKey: 'pressReleases' },
        events: [
            { date: '2026-11-02', period: 'T3 2026', url: 'https://alx-inc.com/press-release/news-details/2026/Alexanders-AnnouncesThird-Quarter-Financial-Results/default.aspx' },
        ],
        verifiedOn: '2026-11-15',
    },
    'CNQ.TO': {
        name: 'Canadian Natural Resources',
        section: { url: 'https://www.cnrl.com/investors', labelKey: 'investorRelations' },
        events: [
            { date: '2026-11-05', period: 'T3 2026', url: 'https://www.cnrl.com/news-releases/canadian-natural-announces-2026-third-quarter-results/' },
        ],
        verifiedOn: '2026-11-15',
    },
    'FFH.TO': {
        name: 'Fairfax Financial',
        section: { url: 'https://www.fairfax.ca/category/press-releases/', labelKey: 'pressReleases' },
        events: [
            { date: '2026-11-03', period: 'T3 2026', url: 'https://www.fairfax.ca/press-releases/fairfax-financial-holdings-limited-financial-results-for-the-third-quarter/' },
        ],
        verifiedOn: '2026-11-15',
    },
    AMRZ: {
        name: 'Amrize',
        section: { url: 'https://investors.amrize.com/', labelKey: 'investorRelations' },
        events: [
            {
                date: '2026-10-28',
                period: 'T3 2026',
                url: 'https://investors.amrize.com/news/detail/141/amrize-reports-third-quarter-2026-results',
                assets: [
                    { kind: 'transcripcion', url: 'https://investors.amrize.com/_assets/_72932955d4a0fda3f58c771077dfbe6d/amrize/db/938/9666/webcast_transcript/Amrize_Q3_2026_Earnings_Call_Transcript.pdf', source: 'https://investors.amrize.com/news/detail/141/amrize-reports-third-quarter-2026-results' },
                ],
            },
        ],
        verifiedOn: '2026-11-15',
    },
    FRPH: {
        // FRP Holdings cotiza como FRPH; su web IR es la de FRP Development.
        name: 'FRP Development (FRPH)',
        section: { url: 'https://investors.frpdev.com/quarterly-reports', labelKey: 'quarterlyResults' },
        events: [
            {
                date: '2026-11-05',
                period: 'T3 2026',
                url: 'https://investors.frpdev.com/quarterly-reports',
                assets: [
                    { kind: 'webcast', url: 'https://www.webcaster5.com/Webcast/Page/3158/54642', source: 'https://investors.frpdev.com/quarterly-reports' },
                    { kind: 'presentacion', url: 'https://irp.cdn-website.com/fa80a5ca/files/uploaded/FRPH+Earnings+Deck+Q3-26+v1+BW.pdf', source: 'https://investors.frpdev.com/quarterly-reports' },
                ],
            },
        ],
        verifiedOn: '2026-11-15',
    },
    'GCC.MX': {
        name: 'GCC',
        section: { url: 'https://ir.gcc.com/en/financiera/overview', labelKey: 'quarterlyResults' },
        events: [
            // Sin pagina por evento: la pagina trimestral lista la presentacion y la transcripcion del 3T26.
            {
                date: '2026-10-27',
                period: 'T3 2026',
                url: 'https://www.gcc.investorcloud.net/en/financiera/overview/trimestrales',
                assets: [
                    { kind: 'presentacion', url: 'https://cdn.investorcloud.net/gcc/InformacionFinanciera/Presentaciones/GCC-Q3-2026-Conference-Call.pdf', source: 'https://www.gcc.investorcloud.net/en/financiera/overview/trimestrales' },
                    { kind: 'transcripcion', url: 'https://cdn.investorcloud.net/gcc/InformacionFinanciera/InformacionTrimestral/ConferenceCall/GCC-Q3-2026-Call-Transcript-.pdf', source: 'https://www.gcc.investorcloud.net/en/financiera/overview/trimestrales' },
                ],
            },
        ],
        verifiedOn: '2026-11-15',
    },
    'WOSG.L': {
        name: 'Watches of Switzerland',
        section: { url: 'https://www.thewosgroupplc.com/news-media/', labelKey: 'pressReleases' },
        events: [
            // Su ejercicio fiscal cierra en abril: esto es el trading update del primer semestre FY27.
            { date: '2026-11-10', period: 'S1 F2027', url: 'https://www.thewosgroupplc.com/media/fvknqdcx/h1-fy27-trading-update.pdf' },
        ],
        verifiedOn: '2026-11-15',
    },
    'MICC.AS': {
        name: 'The Magnum Ice Cream Company',
        section: { url: 'https://corporate.magnumicecream.com/en/investors/results-and-presentations.html', labelKey: 'resultsAndReports' },
        events: [
            { date: '2026-10-29', period: 'T3 2026', url: 'https://news.magnumicecream.com/q3-2026-trading-update/' },
        ],
        verifiedOn: '2026-11-15',
    },
    'SFC.TO': {
        name: 'Sagicor Financial',
        section: { url: 'https://investors.sagicor.com/', labelKey: 'investorRelations' },
        events: [
            { date: '2026-11-11', period: 'T3 2026', url: 'https://investors.sagicor.com/2026-11-11-Sagicor-Financial-Reports-Third-Quarter-2026-Results' },
        ],
        verifiedOn: '2026-11-15',
    },
    'ERF.PA': {
        name: 'Eurazeo',
        section: { url: 'https://www.eurazeo.com/en/shareholders/results-center', labelKey: 'resultsAndReports' },
        events: [
            // Trading update 9M (Eurazeo no publica resultados trimestrales completos).
            { date: '2026-11-05', period: '9M 2026', url: 'https://www.eurazeo.com/sites/default/files/2026-11/Q3-2026-eurazeo-press%20release_.pdf' },
        ],
        verifiedOn: '2026-11-15',
    },
    SKYH: {
        name: 'Sky Harbour',
        section: { url: 'https://ir.skyharbour.group/', labelKey: 'investorRelations' },
        events: [],
        verifiedOn: '2026-11-15',
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

/** Directo oficial verificado del evento: kind 'directo' o, en su defecto, 'webcast'.
 *  Misma regla que el registro: fecha exacta o nada; sin entrada verificada no hay enlace. */
export function irLiveAssetFor(ticker: string, eventDate: string): { asset: IrAsset; verifiedOn: string } | null {
    const links = irLinksFor(ticker, eventDate);
    if (!links) return null;
    const assets = links.eventPage?.assets ?? [];
    const asset = assets.find((a) => a.kind === 'directo') ?? assets.find((a) => a.kind === 'webcast');
    return asset ? { asset, verifiedOn: links.verifiedOn } : null;
}
