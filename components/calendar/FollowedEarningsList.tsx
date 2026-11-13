import type { ReactNode } from 'react';
import Link from 'next/link';
import { ChevronRight, ExternalLink } from 'lucide-react';
import { CompanyLogo } from '@/components/calendar/CompanyLogo';
import { formatMarketDate, type Formatters } from '@/lib/format';

/** Formateador de fechas ligado al idioma activo (getFormat en servidor); sin él, español (tests y render directo). */
type DateFormatter = Pick<Formatters, 'formatMarketDate'>;
import { t, type TranslationKey, type TranslationVars } from '@/lib/i18n/t';

type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;
/** Fallback español sin RequestScope (tests y render directo): el acceso es de main (lib/i18n/t). */
const esT: TiFn = t;
import type { FollowedEarningsEvent } from '@/lib/actions/catalysts.actions';
import type { EventMaterials, MaterialDocument } from '@/lib/earnings-materials';
import { irLinksFor, irLiveAssetFor, type IrSectionLabelKey } from '@/lib/ir-registry';


/** "Sep/2026" -> "T. Sep 2026"; formato desconocido: se muestra tal cual, nunca se reinterpreta. */
export function fiscalLabel(raw: string | null, ti: TiFn = esT): string | null {
    if (!raw) return null;
    const match = /^([A-Za-z]{3})\/(\d{4})$/.exec(raw);
    return match ? ti('calendar.earnings.fiscalClose', { label: `${match[1]} ${match[2]}` }) : raw;
}

/** Título de día al estilo "Mañana, 20 oct" / "mié, 21 oct"; el idioma es el del formateador recibido. */
export function dayHeading(day: string, today: string, ti: TiFn = esT, f?: DateFormatter): string {
    const fmt = f?.formatMarketDate ?? formatMarketDate;
    const base = fmt(day, { weekday: 'short', day: 'numeric', month: 'short' });
    const diff = Math.round((Date.parse(`${day}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
    if (diff === 0) return ti('calendar.earnings.today', { date: fmt(day, { day: 'numeric', month: 'short' }) });
    if (diff === 1) return ti('calendar.earnings.tomorrow', { date: fmt(day, { day: 'numeric', month: 'short' }) });
    return base;
}

// earnings_materials_service.py manda la etiqueta en castellano (KIND_LABEL);
// se nombra por su tipo para que el inglés no la enseñe tal cual.
function materialLabel(doc: MaterialDocument, ti: TiFn): string {
    switch (doc.kind) {
        case 'nota_prensa': return ti('calendar.earnings.materialKind.notaPrensa');
        case 'presentacion': return ti('calendar.earnings.materialKind.presentacion');
        case 'documento': return ti('calendar.earnings.materialKind.documento');
        default: return doc.label;
    }
}

/** Material oficial de la SEC para resultados ya publicados; sin dato = no se pinta nada. */
export function MaterialsLine({ materials, ti = esT, f }: { materials: EventMaterials | undefined; ti?: TiFn; f?: DateFormatter }) {
    const fmt = f?.formatMarketDate ?? formatMarketDate;
    if (!materials || materials.status === 'sin_cobertura_sec' || materials.status === 'periodo_no_coincide') return null;
    if (materials.status === 'no_disponible') {
        return <p className="mt-1 text-xs text-gray-500">{ti('calendar.earnings.materialsUnavailable')}</p>;
    }
    if (materials.status === 'sin_filing' || materials.documents.length === 0) {
        return <p className="mt-1 text-xs text-gray-500">{ti('calendar.earnings.materialsNone')}</p>;
    }
    return (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
            {materials.documents.map((doc) => (
                <a
                    key={doc.url}
                    href={doc.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={ti('calendar.earnings.materialsDocTitle', { exhibit: doc.exhibit, date: fmt(materials.filed_at) })}
                    className="inline-flex items-center gap-1 rounded-md border border-teal-800/60 px-1.5 py-0.5 font-medium text-teal-300 hover:bg-gray-800"
                >
                    {materialLabel(doc, ti)}
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            ))}
            <span className="text-gray-500">{ti('calendar.earnings.materialsSec', { date: fmt(materials.filed_at) })}</span>
        </p>
    );
}

const ASSET_KEY = {
    presentacion: 'calendar.earnings.assetPresentacion',
    directo: 'calendar.earnings.assetDirecto',
    webcast: 'calendar.earnings.assetWebcast',
    grabacion: 'calendar.earnings.assetGrabacion',
    transcripcion: 'calendar.earnings.assetTranscripcion',
} as const;

const IR_SECTION_LABEL: Record<IrSectionLabelKey, TranslationKey> = {
    investorEvents: 'calendar.earnings.irLabels.investorEvents',
    quarterlyResults: 'calendar.earnings.irLabels.quarterlyResults',
    documentsAndEvents: 'calendar.earnings.irLabels.documentsAndEvents',
    eventsAndPresentations: 'calendar.earnings.irLabels.eventsAndPresentations',
    resultsAndReports: 'calendar.earnings.irLabels.resultsAndReports',
    pressReleases: 'calendar.earnings.irLabels.pressReleases',
    investorRelations: 'calendar.earnings.irLabels.investorRelations',
};

/** Enlaces oficiales de IR (registro verificado): pagina del evento si la fecha coincide, si no la seccion general.
 *  `omitLiveAssets`: la fila ya destaca el directo con su propio boton; no duplicar el chip. */
export function IrLine({ ticker, date, ti = esT, omitLiveAssets = false }: { ticker: string; date: string; ti?: TiFn; omitLiveAssets?: boolean }) {
    const links = irLinksFor(ticker, date);
    if (!links) return null;
    const assets = omitLiveAssets
        ? (links.eventPage?.assets ?? []).filter((a) => a.kind !== 'directo' && a.kind !== 'webcast')
        : links.eventPage?.assets;
    const tip = ti('calendar.earnings.irTip', { date: links.verifiedOn });
    const chip = 'inline-flex min-h-[44px] items-center gap-1 rounded-md border border-gray-700 px-1.5 py-0.5 font-medium text-gray-300 hover:bg-gray-800 sm:min-h-0';
    return (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
            {links.eventPage ? (
                <a href={links.eventPage.url} target="_blank" rel="noopener noreferrer" title={tip} className={chip}>
                    {ti('calendar.earnings.irEvent', { period: links.eventPage.period })}
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            ) : (
                <a href={links.section.url} target="_blank" rel="noopener noreferrer" title={`${tip}${ti('calendar.earnings.irTipGeneral')}`} className={chip}>
                    {ti('calendar.earnings.irSection', { label: ti(IR_SECTION_LABEL[links.section.labelKey]) })}
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            )}
            {assets?.map((a) => (
                <a key={a.url} href={a.url} target="_blank" rel="noopener noreferrer" title={ti('calendar.earnings.irAssetTip', { date: links.verifiedOn })} className={chip}>
                    {ti(ASSET_KEY[a.kind])}
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
            ))}
        </p>
    );
}

/** Espera la promesa compartida de materiales (dentro de Suspense) y pinta solo la linea de esta fila. */
export async function EventMaterialsLine({ promise, eventKey, ti = esT, f }: { promise: Promise<Record<string, EventMaterials>>; eventKey: string; ti?: TiFn; f?: DateFormatter }) {
    const all = await promise;
    return <MaterialsLine materials={all[eventKey]} ti={ti} f={f} />;
}

export function FollowedEarningsRow({ event, materialsSlot, ti = esT, today }: { event: FollowedEarningsEvent; materialsSlot?: ReactNode; ti?: TiFn; today?: string }) {
    const session = event.session
        ? ti(event.session === 'pre_market' ? 'calendar.earnings.sessionPreMarket' : 'calendar.earnings.sessionAfterMarket')
        : null;
    const label = fiscalLabel(event.fiscal_label, ti);
    // El directo oficial solo se ofrece el mismo dia del evento y con enlace verificado en el
    // registro IR (fecha exacta). Nunca una hora: la franja publicada sigue visible arriba.
    const isToday = today !== undefined && event.date === today;
    const live = isToday ? irLiveAssetFor(event.ticker, event.date) : null;
    return (
        <li className={`flex items-center gap-3 border-l-2 px-4 py-3 ${isToday ? 'border-blue-500' : 'border-transparent'}`}>
            <CompanyLogo ticker={event.ticker} name={event.company || event.ticker} className="size-12 rounded-xl" />
            <div className="min-w-0 flex-1">
                <p className="truncate text-base font-semibold text-gray-100">{event.company || event.ticker}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-400">
                    <span className="font-mono text-xs text-gray-500">{event.ticker}</span>
                    {session ? (
                        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-200">{session}</span>
                    ) : (
                        <span className="rounded bg-gray-800 px-1.5 py-0.5 text-xs text-gray-400">{ti('calendar.earnings.timeTbc')}</span>
                    )}
                    {label ? <span>{label}</span> : null}
                    {event.confirmed === false ? (
                        <span className="rounded border border-amber-800/60 px-1.5 py-0.5 text-xs text-amber-300">{ti('calendar.earnings.estimated')}</span>
                    ) : null}
                </p>
                {live ? (
                    <p className="mt-1.5 text-xs">
                        <a
                            href={live.asset.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={ti('calendar.earnings.liveWatchTip', { date: live.verifiedOn })}
                            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-md bg-blue-600 px-2.5 py-1 font-semibold text-white hover:bg-blue-500 sm:min-h-0"
                        >
                            {ti('calendar.earnings.liveWatch')}
                            <ExternalLink aria-hidden="true" className="h-3 w-3" />
                        </a>
                    </p>
                ) : null}
                {materialsSlot}
                <IrLine ticker={event.ticker} date={event.date} ti={ti} omitLiveAssets={live !== null} />
            </div>
            {event.source_url ? (
                <a
                    href={event.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={ti('calendar.earnings.docAria', { ticker: event.ticker })}
                    className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-800 hover:text-gray-200 sm:h-9 sm:w-9"
                >
                    <ExternalLink aria-hidden="true" className="h-4 w-4" />
                </a>
            ) : null}
            <Link
                href={`/research/${encodeURIComponent(event.ticker)}`}
                aria-label={ti('calendar.earnings.openAria', { name: event.company || event.ticker })}
                className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-800 hover:text-gray-100 sm:h-9 sm:w-9"
            >
                <ChevronRight aria-hidden="true" className="h-5 w-5" />
            </Link>
        </li>
    );
}
