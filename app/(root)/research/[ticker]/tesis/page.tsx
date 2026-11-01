import { getLocale, getT } from '@/lib/i18n/server';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { TranslationKey } from '@/lib/i18n/t';
import { canShowThesisText, WithheldThesisText } from '@/components/research/ThesisSummary';
import type { Metadata } from 'next';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { ArrowLeft, ChevronDown, FileDown, FileText } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { ErrorState } from '@/components/ui/error-state';
import { AppError } from '@/lib/types/errors';
import { createFormatters, naFor } from '@/lib/format';
import {
  getResearchCompanySnapshot,
  getResearchThesisWorkspace,
} from '@/lib/actions/research.actions';
import { thesisMoney } from '@/lib/research/thesis-number-format';
import { cleanThesisText } from '@/lib/research/thesis-text';
import { readingSections } from '@/lib/research/thesis-reading-sections';
import { isValidCurrencyCode } from '@/lib/format';
import PrintButton from '@/components/research/PrintButton';
import ThesisGenerateButton from '@/components/research/ThesisGenerateButton';
import { ExpertThesisPanel } from '@/components/research/ExpertThesisPanel';
import { getExpertThesis } from '@/lib/actions/expert-thesis.actions';
import { PROVENANCE_GROUPS, provenanceBasis, provenanceGroup } from '@/lib/research/provenance-groups';
import { isVerifiedOficial, provenanceUrls } from '@/lib/research/provenance-item';
import { capitalizeLabel, formatProvenanceValue } from '@/lib/research/provenance-format';
import { metricLabel } from '@/lib/research/metric-labels';
import { publicEditorial } from '@/lib/public-fonts-editorial';
import { cn } from '@/lib/utils';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('research.thesisDoc.metaTitle'), description: t('research.thesisDoc.metaDescription') };
}

type PageProps = {
  params: Promise<{ ticker: string }>;
  searchParams?: Promise<{ expertRun?: string | string[] }>;
};

/** `?expertRun=N` abre entera una corrida anterior del equipo de expertos. */
function parseExpertRun(raw: string | string[] | undefined): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (!value || !/^\d{1,9}$/.test(value)) return null;
  const run = Number(value);
  return run > 0 ? run : null;
}

const STATUS_LABELS: Record<string, string> = {
  draft: 'borrador',
  draft_failed_audit: 'borrador (auditoría no superada)',
  review: 'en revisión',
  final: 'generada · pendiente de aprobación',
  approved: 'aprobada',
  published: 'publicada',
  rejected: 'rechazada',
  stale: 'desactualizada',
  superseded: 'sustituida',
  insufficient_data: 'datos insuficientes',
};

const STATUS_KEYS: Record<string, TranslationKey> = {
  final: 'research.memo.statusFinal', draft: 'research.memo.statusDraft', review: 'research.memo.statusReview',
  approved: 'research.memo.statusApproved', published: 'research.memo.statusPublished', rejected: 'research.memo.statusRejected',
  stale: 'research.memo.statusStale', draft_failed_audit: 'research.memo.statusDraftFailedAudit',
  superseded: 'research.thesisDoc.statusSuperseded', insufficient_data: 'research.memo.insufficientData',
};

const RATING_KEYS: Record<string, TranslationKey> = {
  buy: 'research.memo.ratingBuy', accumulate: 'research.memo.ratingAccumulate', overweight: 'research.memo.ratingOverweight',
  hold: 'research.memo.ratingHold', underweight: 'research.memo.ratingUnderweight', trim: 'research.memo.ratingTrim',
  sell: 'research.memo.ratingSell', avoid: 'research.memo.ratingAvoid', watch: 'research.memo.ratingWatch',
  attractive: 'research.memo.ratingAttractive', expensive: 'research.memo.ratingExpensive',
  incomplete_price: 'research.memo.ratingIncompletePrice', blocked: 'research.memo.ratingBlocked', insufficient_data: 'research.memo.insufficientData',
};

const PROVENANCE_GROUP_KEYS: Record<string, TranslationKey> = {
  reportado: 'research.memo.provReported', sin_verificar: 'research.memo.provUnverified',
  calculado: 'research.memo.provCalculated', supuesto: 'research.memo.provAssumption',
};

/** En español, los mapas de arriba tal cual; en inglés, las claves del memo. */
function statusLabel(status: string | null | undefined, t: TranslateFn, locale: Locale): string {
  if (!status) return t('research.thesisDoc.statusUnknown');
  if (locale === 'en') return Object.hasOwn(STATUS_KEYS, status) ? t(STATUS_KEYS[status]) : t('research.thesisDoc.statusUnknown');
  return STATUS_LABELS[status] ?? 'desconocido';
}

function ratingLabel(rating: string, t: TranslateFn, locale: Locale): string {
  if (locale === 'en') return Object.hasOwn(RATING_KEYS, rating) ? t(RATING_KEYS[rating]) : rating.replaceAll('_', ' ');
  return RATING_LABELS[rating] ?? rating;
}

const RATING_LABELS: Record<string, string> = {
  buy: 'compra', accumulate: 'acumular', overweight: 'sobreponderar',
  hold: 'mantener', underweight: 'infraponderar', trim: 'recortar',
  sell: 'venta', avoid: 'evitar', watch: 'seguimiento',
  attractive: 'atractiva', expensive: 'cara',
  incomplete_price: 'precio incompleto', blocked: 'bloqueada',
  insufficient_data: 'datos insuficientes',
};

function money(value: string | null, currency: string | null | undefined, locale: Locale = 'es'): string {
  if (value === null) return naFor(locale);
  const parsed = Number(value);
  if (Number.isNaN(parsed) || !isValidCurrencyCode(currency)) return naFor(locale);
  return thesisMoney(parsed, currency, locale);
}

/*
 * Tipografia de lectura. La vista es un documento largo: medida de ~70
 * caracteres (40rem a 16px), interlineado 1,75 y titulos de seccion en la
 * serif editorial con tinta clara. Antes cada h2 iba en teal (catorce veces
 * el acento por pantalla) a 95 caracteres por linea e interlineado doble.
 */
const EDITORIAL = { fontFamily: 'var(--font-editorial), Georgia, serif' };
const PARAGRAPH = 'mt-3 text-base leading-7 text-gray-200';
const LIST = 'mt-3 list-disc space-y-2 pl-5 text-base leading-7 text-gray-200 marker:text-gray-500';
const EXPORT_LINK = cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'font-medium');

type TocItem = { id: string; title: string };

function SectionTitle({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} style={EDITORIAL} className="scroll-mt-24 text-2xl leading-tight text-gray-50">
      {children}
    </h2>
  );
}

/**
 * Indice del documento. En escritorio es una columna fija a la derecha del
 * texto; en movil, un desplegable cerrado bajo la cabecera (no empuja la
 * lectura). No se imprime: el papel ya tiene su orden.
 */
function ThesisToc({ items, variant, t }: { items: TocItem[]; variant: 'aside' | 'inline'; t: TranslateFn }) {
  if (items.length < 3) return null;
  const list = (
    <ol className="space-y-1 text-sm">
      {items.map((item) => (
        <li key={item.id}>
          <a
            href={`#${item.id}`}
            className="flex min-h-11 items-center rounded-md px-2 text-gray-400 transition-colors hover:bg-gray-800/60 hover:text-gray-100 lg:min-h-0 lg:py-1"
          >
            {item.title}
          </a>
        </li>
      ))}
    </ol>
  );
  if (variant === 'inline') {
    return (
      <details className="group rounded-lg border border-gray-800 print:hidden lg:hidden">
        <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-3 text-sm text-gray-300 [&::-webkit-details-marker]:hidden">
          {t('research.thesisDoc.tocToggle')}
          <ChevronDown aria-hidden="true" className="h-4 w-4 text-gray-500 transition-transform group-open:rotate-180" />
        </summary>
        <nav aria-label={t('research.thesisDoc.tocAria')} className="border-t border-gray-800 px-1 py-2">{list}</nav>
      </details>
    );
  }
  return (
    <aside className="hidden print:hidden lg:block">
      <nav aria-label={t('research.thesisDoc.tocAria')} className="sticky top-[calc(var(--shell-top)+1.5rem)]">
        <p className="px-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{t('research.thesisDoc.tocTitle')}</p>
        <div className="mt-2 border-l border-gray-800 pl-2">{list}</div>
      </nav>
    </aside>
  );
}

/** Dominio legible de una fuente («sec.gov»), sin IDs internos ni la URL entera. */
function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return 'fuente';
  }
}

type ThesisLike = {
  executive_summary?: string | null;
  hypothesis?: string | null;
  narrative_sections?: { titulo: string; parrafos: string[] }[] | null;
  thesis_markdown?: string | null;
  catalysts?: { label?: string | null; date?: string | null }[] | null;
  invalidation_criteria?: string[] | null;
};

const narrativeId = (index: number) => `seccion-${index + 1}`;

function tocFor(thesis: ThesisLike, extra: { provenance: boolean; fromMarkdown?: boolean }, t: TranslateFn): TocItem[] {
  const sections = extra.fromMarkdown ? readingSections(thesis) : (thesis.narrative_sections ?? []);
  return [
    thesis.executive_summary ? { id: 'resumen', title: t('research.thesisDoc.summary') } : null,
    thesis.hypothesis ? { id: 'hipotesis', title: t('research.thesisDoc.hypothesis') } : null,
    { id: 'escenarios', title: t('research.thesisDoc.scenarios') },
    extra.provenance ? { id: 'procedencia', title: t('research.thesisDoc.provenance') } : null,
    ...sections.map((section, index) => ({ id: narrativeId(index), title: section.titulo })),
    (thesis.catalysts ?? []).length > 0 ? { id: 'catalizadores', title: t('research.thesisDoc.catalysts') } : null,
    (thesis.invalidation_criteria ?? []).length > 0 ? { id: 'invalidacion', title: t('research.thesisDoc.invalidation') } : null,
  ].filter((item): item is TocItem => item !== null);
}

/**
 * Vista de lectura de la tesis PUBLICADA: documento limpio, imprimible y
 * descargable (PDF/Markdown). Solo lo que contiene la version publicada;
 * un borrador mas reciente se anuncia sin cifras ni margen (regla vigente).
 */
export default async function ThesisReadingPage({ params, searchParams }: PageProps) {
  const [t, locale] = await Promise.all([getT(), getLocale()]);
  const { formatGeneratedDate, formatPercent, formatUserDate } = createFormatters(locale);
  const { ticker: rawTicker } = await params;
  const ticker = rawTicker.toUpperCase();
  const expertRun = parseExpertRun((await searchParams)?.expertRun);

  const [snapshotRead, workspace, expertThesis] = await Promise.all([
    // null = 404 «compañía ausente del master» (getResearchCompanySnapshot
    // solo devuelve null ahí); cualquier otro fallo es `failed`. Antes ambos
    // eran null y un ticker fuera del master se contaba como caída del servicio.
    getResearchCompanySnapshot(ticker).then(
      (value) => ({ value, failed: false }),
      () => ({ value: null, failed: true }),
    ),
    getResearchThesisWorkspace(ticker).catch(() => null),
    // Tesis del equipo de expertos (EXPERT_TEAM_ENABLED): null si está apagado o no hay.
    // Con ?expertRun=N, esa corrida; si no es tuya o no existe, la última.
    getExpertThesis(ticker, expertRun).then((found) => (found || !expertRun ? found : getExpertThesis(ticker))),
  ]);
  const snapshot = snapshotRead.value;
  const company = snapshot?.company ?? null;
  const currency = company?.currency ?? null;
  const latest = workspace?.thesis ?? null;
  // `getResearchThesisWorkspace` devuelve `thesis: null` cuando NO hay tesis
  // (404) y lanza cuando el backend falla: `workspace === null` es un fallo,
  // no un «todavía no hay tesis». Lo mismo con las versiones.
  const versions = workspace ? await readLatestPublished(ticker) : { published: null, failed: false, missing: false };
  const published = versions.published;
  // Fuentes por cifra: /versions no las trae; /latest si. Solo se muestran
  // cuando la publicada ES la ultima version: la procedencia de un borrador
  // mas nuevo no describe este documento y afirmarlo seria inventarlo.
  const provenance =
    published && latest && latest.id === published.id
      ? (latest.inputs_provenance ?? null)
      : null;

  const encoded = encodeURIComponent(ticker);
  const name = company?.name ?? ticker;
  const generated = published ? formatGeneratedDate(published.created_at) : null;
  // El precio persistido con la versión es el que usó el MODELO al generarla
  // (snapshot de posición o último cierre), no la cotización de hoy: nunca
  // se rotula "Precio actual". La fecha de la cotización solo se muestra si
  // el motor la persistió en valuation_basis; si no, sin fecha (no se inventa).
  const priceAsOf = published?.valuation_basis?.price_as_of ?? null;
  const modelPriceLabel = priceAsOf
    ? t('research.thesisDoc.modelPriceAt', { date: formatUserDate(priceAsOf) })
    : t('research.thesisDoc.modelPrice');
  // La columna Probabilidad solo se muestra cuando el motor persistio
  // probabilidades: sin ellas seria un «N/D» triple que aparenta un dato
  // que no existe (regla de veracidad: no inventar ni insinuar datos).
  const hasProbabilities = published
    ? [published.scenario_probabilities?.bear,
       published.scenario_probabilities?.base,
       published.scenario_probabilities?.bull].some((p) => typeof p === 'number')
    : false;
  // Sin valores de escenario (p. ej. insufficient_data) la tabla no se
  // pinta: serian tres filas de «N/D» aparentando una valoracion que el
  // modelo no produjo. Las probabilidades pueden existir aun sin valores
  // (el motor las persiste aparte), pero sin valores no hay tabla que
  // acompanar: se dice tal cual.
  const hasScenarioValues = published
    ? [published.bear_value, published.base_value, published.bull_value].some((v) => v !== null)
    : false;

  // Retain all persisted free text and numeric values together. A missing
  // snapshot is not evidence of publishability, even for a published archive.
  const displayedVersion = published ?? latest;
  // Sin snapshot no se puede evaluar la puerta de publicacion: si habia una
  // version que mostrar, eso es un fallo de carga y se dice como tal.
  // Ticker fuera del master: el snapshot dio 404 y /versions también (o no hay
  // nada que mostrar). No es un fallo del servicio: no hay tesis porque la
  // empresa no está en la cobertura. Se dice tal cual, sin «Reintentar».
  const companyMissing =
    workspace !== null && !snapshotRead.failed && snapshot === null
    && (versions.missing || displayedVersion === null);
  const loadFailed = !companyMissing && (
    workspace === null || versions.failed || (displayedVersion !== null && snapshot === null)
  );
  if (!loadFailed && displayedVersion && !canShowThesisText(displayedVersion, snapshot?.model_summary)) {
    return (
      <main id="content" className={`print-document min-h-screen bg-surface-0 text-gray-100 ${publicEditorial.variable}`}>
        <div className="mx-auto max-w-[40rem]">
          <Link href={`/research/${encoded}?view=thesis`} className="text-sm text-teal-300 underline">{t('research.thesisDoc.backToFicha', { ticker })}</Link>
          <h1 className="mt-8 text-3xl text-gray-50">{ticker} · {name}</h1>
          <WithheldThesisText thesis={displayedVersion} model={snapshot?.model_summary} locale={locale} />
          <p className="mt-4 text-sm leading-6 text-gray-400">{t('research.thesisDoc.withheldNote')}</p>
          {/*
              Salida del callejón (auditoría 29-oct-2026): la nota de archivo
              sin acción dejaba la página sin ruta a seguir. Acción principal:
              la ficha, donde están las fuentes y los datos pendientes que
              cita el párrafo. Secundaria: regenerar, el mismo botón y estados
              honestos de job que ofrece la ficha.
          */}
          <div className="mt-6 flex flex-wrap items-center gap-2">
            <EmptyLink href={`/research/${encoded}?view=thesis`}>{t('research.thesisDoc.reviewInFicha')}</EmptyLink>
            <ThesisGenerateButton ticker={ticker} label={t('research.thesisDoc.regenerate')} />
          </div>
        </div>
      </main>
    );
  }

  const toc = published
    ? tocFor(published, { provenance: Boolean(provenance && provenance.length > 0), fromMarkdown: true }, t)
    : latest
      ? tocFor(latest, { provenance: false }, t)
      : [];

  return (
    <main id="content" className={`print-document min-h-screen bg-surface-0 text-gray-100 ${publicEditorial.variable}`}>
      <div className="mx-auto max-w-5xl">
        <div className="print:hidden">
          <Link
            href={`/research/${encoded}?view=thesis`}
            className="inline-flex min-h-[44px] items-center text-sm text-gray-500 hover:text-gray-200 sm:min-h-0"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />{t('research.thesisDoc.backToFicha', { ticker })}
          </Link>
        </div>

        {companyMissing ? (
          <div className="mt-8 max-w-[40rem]">
            <EmptyState
              action={(
                <div className="flex flex-wrap items-center justify-center gap-3">
                  <EmptyLink href={`/research/${encoded}`}>{t('research.thesisDoc.checkTicker', { ticker })}</EmptyLink>
                  <EmptyLink href="/search">{t('research.thesisDoc.searchOther')}</EmptyLink>
                </div>
              )}
              description={t('research.thesisDoc.notCoveredDescription', { ticker })}
              title={t('research.thesisDoc.notCoveredTitle', { ticker })}
              titleAs="h1"
            />
          </div>
        ) : loadFailed ? (
          <div className="mt-8 max-w-[40rem]">
            <ErrorState
              action={(
                <>
                  <a className={EXPORT_LINK} href={`/research/${encoded}/tesis`}>{t('research.thesisDoc.retry')}</a>
                  <Link className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }), 'font-medium')} href={`/research/${encoded}?view=thesis`}>{t('research.thesisDoc.goToFicha')}</Link>
                </>
              )}
              description={t('research.thesisDoc.loadFailedDescription', { ticker })}
              title={t('research.thesisDoc.loadFailedTitle', { ticker })}
              titleAs="h1"
            />
          </div>
        ) : !published && latest && latest.status === 'insufficient_data' ? (
          <div className="mt-6 lg:grid lg:grid-cols-[minmax(0,40rem)_13rem] lg:justify-between lg:gap-12">
          <article className="min-w-0 max-w-full space-y-10 [overflow-wrap:anywhere]">
            <header className="space-y-4 border-b border-gray-800 pb-6">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{t('research.thesisDoc.eyebrow')}</p>
              <h1 style={EDITORIAL} className="text-3xl leading-tight text-gray-50 sm:text-4xl">
                {ticker} · {name}
              </h1>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="thesis-meta-badge" variant="outline">{t('research.thesisDoc.provisionalBadge')}</Badge>
                <Badge className="thesis-meta-badge" variant="outline">{statusLabel(latest.status, t, locale)}</Badge>
                <Badge className="thesis-meta-badge" variant="outline">v{latest.version}</Badge>
                {latest.created_at ? <span className="text-xs text-gray-500">{t('research.thesisDoc.generatedOn', { date: formatGeneratedDate(latest.created_at) ?? '' })}</span> : null}
              </div>
              <p role="status" className="rounded-lg border border-amber-800/60 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
                {t('research.thesisDoc.provisionalNote')}
              </p>
              <div className="flex flex-wrap items-center gap-2 print:hidden">
                <PrintButton />
                <a
                  href={`/api/thesis/${encoded}/pdf?draft=1`}
                  download
                  className={EXPORT_LINK}
                >
                  <FileDown className="h-4 w-4" />{t('research.thesisDoc.draftPdf', { version: latest.version })}
                </a>
                <EmptyLink href={`/research/${encoded}?view=thesis`}>{t('research.thesisDoc.reviewVersion', { version: latest.version })}</EmptyLink>
              </div>
              <p className="text-xs text-gray-500 print:hidden">
                {t('research.thesisDoc.draftPdfNote')}
              </p>
              <ThesisToc items={toc} variant="inline" t={t} />
            </header>

            {latest.executive_summary ? (
              <section>
                <SectionTitle id="resumen">{t('research.thesisDoc.summary')}</SectionTitle>
                <p className={PARAGRAPH}>{cleanThesisText(latest.executive_summary)}</p>
              </section>
            ) : null}

            {latest.hypothesis ? (
              <section>
                <SectionTitle id="hipotesis">{t('research.thesisDoc.hypothesis')}</SectionTitle>
                <p className={PARAGRAPH}>{cleanThesisText(latest.hypothesis)}</p>
              </section>
            ) : null}

            <section>
              <SectionTitle id="escenarios">{t('research.thesisDoc.scenarios')}</SectionTitle>
              <p className="mt-4 text-sm leading-6 text-gray-400">
                {t('research.thesisDoc.draftNoFigures')}
              </p>
            </section>

            {(latest.narrative_sections ?? []).map((section, index) => (
              <section key={section.titulo}>
                <SectionTitle id={narrativeId(index)}>{section.titulo}</SectionTitle>
                {section.parrafos.map((parrafo, paragraphIndex) => (
                  <p key={paragraphIndex} className={PARAGRAPH}>{cleanThesisText(parrafo)}</p>
                ))}
              </section>
            ))}

            {(latest.catalysts ?? []).length > 0 ? (
              <section>
                <SectionTitle id="catalizadores">{t('research.thesisDoc.catalysts')}</SectionTitle>
                <ul className={LIST}>
                  {(latest.catalysts ?? []).map((catalyst, index) => (
                    <li key={index}>
                      {catalyst.label ?? t('research.thesisDoc.catalyst')}{catalyst.date ? ` (${formatUserDate(catalyst.date)})` : ''}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {(latest.invalidation_criteria ?? []).length > 0 ? (
              <section>
                <SectionTitle id="invalidacion">{t('research.thesisDoc.invalidation')}</SectionTitle>
                <ul className={LIST}>
                  {(latest.invalidation_criteria ?? []).map((criterion, index) => (
                    <li key={index}>{criterion}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            <footer className="border-t border-gray-800 pt-4 text-xs leading-6 text-gray-500">
              <p>
                {t('research.thesisDoc.draftScores', { data: latest.data_confidence_score ?? '', sources: latest.source_coverage_score ?? '', redTeam: latest.red_team_score ?? '' })}
              </p>
              <p className="mt-2">
                {t('research.thesisDoc.draftDisclaimer')}
              </p>
            </footer>
          </article>
          <ThesisToc items={toc} variant="aside" t={t} />
          </div>
        ) : !published ? (
          <div className="mt-10">
            <EmptyState
              action={latest ? <EmptyLink href={`/research/${encoded}?view=thesis`}>{t('research.thesisDoc.reviewVersion', { version: latest.version })}</EmptyLink> : <EmptyLink href={`/research/${encoded}`}>{t('research.thesisDoc.generateFirst')}</EmptyLink>}
              description={latest ? t('research.thesisDoc.notPublishedDescription', { version: latest.version, status: statusLabel(latest.status, t, locale) }) : t('research.thesisDoc.noneDescription', { ticker })}
              title={t('research.thesisDoc.noPublishedTitle', { ticker })}
              titleAs="h1"
            />
          </div>
        ) : (
          <div className="mt-6 lg:grid lg:grid-cols-[minmax(0,40rem)_13rem] lg:justify-between lg:gap-12">
          <article className="min-w-0 max-w-full space-y-10 [overflow-wrap:anywhere]">
            <header className="space-y-4 border-b border-gray-800 pb-6">
              <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{t('research.thesisDoc.eyebrow')}</p>
              <h1 style={EDITORIAL} className="text-3xl leading-tight text-gray-50 sm:text-4xl">
                {ticker} · {name}
              </h1>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className="thesis-meta-badge" variant="outline">{t('research.thesisDoc.ratingBadge', { rating: ratingLabel(published.rating, t, locale) })}</Badge>
                <Badge className="thesis-meta-badge" variant="outline">v{published.version}</Badge>
                {generated ? <span className="text-xs text-gray-500">{t('research.thesisDoc.generatedOn', { date: generated })}</span> : null}
              </div>
              {latest && latest.version !== published.version ? (
                <p className="text-xs text-amber-300">
                  {t('research.thesisDoc.newerDraft', { version: latest.version })}
                </p>
              ) : null}
              {published ? (
              <div className="flex flex-wrap items-center gap-2 print:hidden">
                <a
                  href={`/api/thesis/${encoded}/pdf`}
                  download
                  className={EXPORT_LINK}
                >
                  <FileDown className="h-4 w-4" />PDF
                </a>
                <a
                  href={`/api/thesis-memo/${encoded}`}
                  download
                  className={EXPORT_LINK}
                >
                  <FileText className="h-4 w-4" />Markdown
                </a>
                <PrintButton />
              </div>
              ) : null}
              <ThesisToc items={toc} variant="inline" t={t} />
            </header>

            {published.executive_summary ? (
              <section>
                <SectionTitle id="resumen">{t('research.thesisDoc.summary')}</SectionTitle>
                <p className={PARAGRAPH}>{cleanThesisText(published.executive_summary)}</p>
              </section>
            ) : null}

            {published.hypothesis ? (
              <section>
                <SectionTitle id="hipotesis">{t('research.thesisDoc.hypothesis')}</SectionTitle>
                <p className={PARAGRAPH}>{cleanThesisText(published.hypothesis)}</p>
              </section>
            ) : null}

            <section>
              <SectionTitle id="escenarios">{t('research.thesisDoc.scenarios')}</SectionTitle>
              {hasScenarioValues ? (
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700 text-left text-xs uppercase tracking-wide text-gray-500">
                      <th scope="col" className="py-2 pr-4 font-medium">{t('research.thesisDoc.colScenario')}</th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">{t('research.thesisDoc.colValue')}</th>
                      {hasProbabilities ? <th scope="col" className="py-2 text-right font-medium">{t('research.thesisDoc.colProbability')}</th> : null}
                    </tr>
                  </thead>
                  <tbody className="text-gray-200">
                    {([
                      [t('research.thesisDoc.bear'), published.bear_value, published.scenario_probabilities?.bear],
                      [t('research.thesisDoc.base'), published.base_value, published.scenario_probabilities?.base],
                      [t('research.thesisDoc.bull'), published.bull_value, published.scenario_probabilities?.bull],
                    ] as const).map(([label, value, probability]) => (
                      <tr key={label} className="border-b border-gray-800/70">
                        <th scope="row" className="py-2 pr-4 text-left font-normal text-gray-400">{label}</th>
                        <td className="py-2 pr-4 text-right font-medium tabular-nums">{money(value, currency, locale)}</td>
                        {hasProbabilities ? (
                          <td className="py-2 text-right tabular-nums">{typeof probability === 'number' ? formatPercent(probability, { digits: 0 }) : naFor(locale)}</td>
                        ) : null}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              ) : (
                <p className="mt-4 text-sm text-gray-400">{t('research.thesisDoc.noFigures')}</p>
              )}
              <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-xs text-gray-500">{modelPriceLabel}</dt>
                  <dd className="mt-0.5 font-medium tabular-nums text-gray-100">{money(published.current_price, currency, locale)}</dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">{t('research.thesisDoc.expectedValue')}</dt>
                  <dd className="mt-0.5 font-medium tabular-nums text-gray-100">{money(published.expected_value, currency, locale)}</dd>
                </div>
                {published.margin_of_safety !== null ? (
                  <div>
                    <dt className="text-xs text-gray-500">{t('research.thesisDoc.marginOfSafety')}</dt>
                    <dd className="mt-0.5 font-medium tabular-nums text-gray-100">{formatPercent(Number(published.margin_of_safety))}</dd>
                  </div>
                ) : null}
              </dl>
            </section>

            {provenance && provenance.length > 0 ? (
              <section>
                <SectionTitle id="procedencia">{t('research.thesisDoc.provenance')}</SectionTitle>
                <div className="mt-4 space-y-5">
                  {PROVENANCE_GROUPS.map((group) => {
                    const rows = provenance.filter(
                      (item) => provenanceGroup(item.label as string | undefined, isVerifiedOficial(item)) === group.key,
                    );
                    if (rows.length === 0) return null;
                    return (
                      <div key={group.key}>
                        <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">{Object.hasOwn(PROVENANCE_GROUP_KEYS, group.key) ? t(PROVENANCE_GROUP_KEYS[group.key]) : group.title}</h3>
                        <dl className="mt-1 divide-y divide-gray-800/70">
                          {rows.map((item) => {
                            const urls = provenanceUrls(item);
                            const basis = provenanceBasis(item.base_inferencia ?? item.method, locale);
                            const label = capitalizeLabel(metricLabel(item.key, locale));
                            return (
                              <div key={item.key} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2 text-sm">
                                <dt className="text-gray-300">{label}</dt>
                                <dd className="ml-auto font-medium tabular-nums text-gray-100">{formatProvenanceValue(item.value, item.unit)}</dd>
                                <dd className="basis-full text-xs leading-5 text-gray-500">
                                  {basis ?? t('research.thesisDoc.basisUndocumented')}
                                  {urls.map((url, index) => (
                                    <a
                                      key={url}
                                      href={url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      aria-label={t('research.thesisDoc.sourceAria', { n: index + 1, label, host: sourceHost(url) })}
                                      className="ml-2 text-gray-300 underline decoration-gray-600 underline-offset-2 hover:text-gray-100 hover:decoration-gray-300 print:text-gray-700 print:no-underline"
                                    >
                                      {sourceHost(url)}
                                    </a>
                                  ))}
                                </dd>
                              </div>
                            );
                          })}
                        </dl>
                      </div>
                    );
                  })}
                </div>
              </section>
            ) : null}

            {/* A10: una tesis antigua sin secciones se lee desde su memo markdown. */}
            {readingSections(published).map((section, index) => (
              <section key={section.titulo}>
                <SectionTitle id={narrativeId(index)}>{section.titulo}</SectionTitle>
                {section.parrafos.map((parrafo, paragraphIndex) => (
                  <p key={paragraphIndex} className={PARAGRAPH}>{cleanThesisText(parrafo)}</p>
                ))}
              </section>
            ))}

            {(published.catalysts ?? []).length > 0 ? (
              <section>
                <SectionTitle id="catalizadores">{t('research.thesisDoc.catalysts')}</SectionTitle>
                <ul className={LIST}>
                  {(published.catalysts ?? []).map((catalyst, index) => (
                    <li key={index}>
                      {catalyst.label ?? t('research.thesisDoc.catalyst')}{catalyst.date ? ` (${formatUserDate(catalyst.date)})` : ''}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {(published.invalidation_criteria ?? []).length > 0 ? (
              <section>
                <SectionTitle id="invalidacion">{t('research.thesisDoc.invalidation')}</SectionTitle>
                <ul className={LIST}>
                  {(published.invalidation_criteria ?? []).map((criterion, index) => (
                    <li key={index}>{criterion}</li>
                  ))}
                </ul>
              </section>
            ) : null}

            <footer className="border-t border-gray-800 pt-4 text-xs leading-6 text-gray-500">
              <p>
                {t('research.thesisDoc.evidenceScores', { data: published.data_confidence_score ?? '', sources: published.source_coverage_score ?? '', redTeam: published.red_team_score ?? '' })}
              </p>
              <p className="mt-2">
                {t('research.thesisDoc.disclaimer')}
              </p>
            </footer>
          </article>
          <ThesisToc items={toc} variant="aside" t={t} />
          </div>
        )}
        {!companyMissing && !loadFailed ? (
          <div className="max-w-[40rem]">
            <ExpertThesisPanel
              thesis={expertThesis}
              t={t}
              formatDate={formatUserDate}
              basePath={`/research/${encodeURIComponent(ticker)}/tesis`}
            />
          </div>
        ) : null}
      </div>
    </main>
  );
}

/**
 * La publicada con contenido completo: /versions trae cada version entera.
 * Un fallo de red o del backend vuelve como `failed`, nunca como «no hay
 * publicada»: la pagina lo pinta como error con reintento.
 */
async function readLatestPublished(ticker: string) {
  const { researchRequest } = await import('@/lib/research/client');
  type Version = NonNullable<Awaited<ReturnType<typeof getResearchThesisWorkspace>>['thesis']>;
  let versions: Version[] = [];
  try {
    versions = await researchRequest<Version[]>(
      `/api/thesis/${encodeURIComponent(ticker)}/versions`,
      { timeoutMs: 12_000 },
    );
  } catch (error) {
    // 404 = «Company not found» (ticker fuera del master): no es un fallo.
    if (error instanceof AppError && error.statusCode === 404) {
      return { published: null, failed: false, missing: true };
    }
    return { published: null, failed: true, missing: false };
  }
  const published = versions
    .filter((version) => version.status === 'published')
    .sort((a, b) => b.version - a.version)[0];
  return { published: published ?? null, failed: false, missing: false };
}
