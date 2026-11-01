import type {
  InvestorDatum,
  InvestorPortfolio,
} from "@/lib/actions/investors.actions";
import { ownershipLimitations } from "@/lib/research/ownership-display";
import { createFormatters } from "@/lib/format";
import type { Locale } from "@/lib/i18n/locale";
import { getLocale, getT } from "@/lib/i18n/server";
import { Pagination, paginate } from "./Pagination";
import { periodLabel } from "./format";

const ACTIONS: Record<string, string> = {
  compra: "Compra",
  venta: "Venta",
  nueva: "Nueva",
  cerrada: "Cerrada",
  aumento: "Aumento",
  reduccion: "Reducción",
  donacion: "Donación",
  alta: "Alta",
  otro: "Otro",
  sin_datos: "Sin datos",
  concesion: "Concesión",
  ejercicio: "Ejercicio",
  retencion: "Retención",
};

const ACTIONS_EN: Record<string, string> = {
  compra: "Buy",
  venta: "Sell",
  nueva: "New",
  cerrada: "Closed",
  aumento: "Increased",
  reduccion: "Reduced",
  donacion: "Gift",
  alta: "Added",
  otro: "Other",
  sin_datos: "Unavailable",
  concesion: "Grant",
  ejercicio: "Exercise",
  retencion: "Tax withholding",
};

export function Datum({
  datum,
  kind = "number",
  locale = "es",
}: {
  datum: InvestorDatum;
  kind?: "number" | "usd" | "percent";
  locale?: Locale;
}) {
  const fmt = createFormatters(locale);
  const NA = fmt.na;
  // Fail closed even if a malformed payload claims OFICIAL without a dated source.
  const available =
    datum.value !== null &&
    Number.isFinite(datum.value) &&
    datum.label !== "SIN_DATOS" &&
    datum.as_of &&
    (datum.label !== "OFICIAL" || datum.source_url);
  // El código interno SIN_DATOS nunca se pinta crudo: la convención de la
  // app para un dato ausente es «N/D».
  const text = !available
    ? NA
    : kind === "usd"
      ? fmt.formatMarketCapUsd(datum.value)
      : kind === "percent"
        ? fmt.formatPercent(datum.value, { fromRatio: false })
        : fmt.formatNumber(datum.value);
  return (
    <span className="flex flex-col gap-1">
      <span className="font-medium text-gray-100">{text}</span>
      {available ? (
        <span className="text-xs text-gray-500">
          {periodLabel(datum.as_of, locale)}
        </span>
      ) : null}
    </span>
  );
}

/** Peso en cartera: si el backend no lo trae (SIN_DATOS) pero el valor de
 *  la posición y el total de la cartera sí son datos, se calcula
 *  valor / total — dos cifras declaradas, nada inventado — con la fecha y
 *  fuente del total. Sin total fiable queda N/D. La etiqueta interna queda
 *  INFERIDO (puerta de la barra de distribución) pero NO se pinta en UI:
 *  decisión de Nico (16-oct), la app no marca «inferido». */
function derivedWeight(
  row: InvestorPortfolio["positions"][number],
  total: InvestorDatum,
): InvestorDatum {
  const declared = row.weight_pct;
  if (
    declared.value !== null &&
    Number.isFinite(declared.value) &&
    declared.label !== "SIN_DATOS"
  ) {
    return declared;
  }
  const value = row.value_usd.value;
  const totalValue = total.value;
  if (
    value !== null &&
    Number.isFinite(value) &&
    totalValue !== null &&
    Number.isFinite(totalValue) &&
    totalValue > 0
  ) {
    return {
      value: (100 * value) / totalValue,
      label: "INFERIDO",
      as_of: total.as_of,
      source_url: total.source_url,
    };
  }
  return declared;
}

export async function Portfolio({
  portfolio,
  view,
  pagina,
}: {
  portfolio: InvestorPortfolio;
  view: string;
  pagina?: string;
}) {
  const t = await getT();
  const locale = await getLocale();
  const actions = locale === "en" ? ACTIONS_EN : ACTIONS;
  const positions = paginate(portfolio.positions, pagina, 20);
  const movements = paginate(portfolio.movements, pagina, 20);
  const paged = view === "cambios" ? movements : positions;
  return (
    <section aria-label={t('investors.portfolio.aria')} className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <Datum datum={portfolio.total_value_usd} kind="usd" locale={locale} />
        <span className="text-sm text-gray-500">
          {portfolio.positions.length === 1
            ? t('investors.portfolio.positionsOne', { count: 1 })
            : t('investors.portfolio.positionsMany', { count: portfolio.positions.length })}
          {portfolio.as_of ? ` · ${periodLabel(portfolio.as_of, locale)}` : ""}
        </span>
      </div>
      {portfolio.coverage === "partial" ? (
        <p role="status" className="text-sm text-amber-300">
          {t('investors.hub.partial')}
        </p>
      ) : null}
      {paged.items.length === 0 ? (
        <p className="text-sm text-gray-500">
          {createFormatters(locale).na}
          {view === "cambios" ? ` · ${t('investors.portfolio.noMovements')}` : ""}
        </p>
      ) : view === "cambios" ? (
        <ul className="divide-y divide-gray-800">
          {movements.items.map((row, index) => (
            <li
              className="flex flex-col gap-3 py-4"
              key={`${row.issuer}-${row.date}-${index}`}
            >
              <div className="flex flex-wrap justify-between gap-2">
                <h3 className="text-sm text-gray-100">{row.issuer}</h3>
                <span className="text-sm text-gray-400">
                  {actions[row.action] ?? actions.otro} · {periodLabel(row.date, locale)}
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div>
                  <p className="mb-1 text-xs text-gray-500">
                    {t('investors.portfolio.sharesChange')}
                  </p>
                  <Datum datum={row.shares} locale={locale} />
                </div>
                <div>
                  <p className="mb-1 text-xs text-gray-500">{t('investors.portfolio.sharesAfter')}</p>
                  <Datum datum={row.shares_after} locale={locale} />
                </div>
                <div>
                  <p className="mb-1 text-xs text-gray-500">{t('investors.portfolio.price')}</p>
                  <Datum datum={row.price_usd} kind="usd" locale={locale} />
                </div>
              </div>
              {row.note ? (
                <p className="text-xs text-gray-500">{row.note}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <ul className="divide-y divide-gray-800">
          {positions.items.map((row, index) => {
            const weight = derivedWeight(row, portfolio.total_value_usd);
            return (
            <li
              className="flex flex-col gap-3 py-4"
              key={`${row.cusip}-${row.title_of_class}-${index}`}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-gray-100">
                  {row.issuer}
                  {row.ticker ? ` · ${row.ticker}` : ""}
                </h3>
                <span className="text-xs text-gray-500">
                  {row.source_form} · {row.title_of_class}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <p className="mb-1 text-xs text-gray-500">{t('investors.portfolio.value')}</p>
                  <Datum datum={row.value_usd} kind="usd" locale={locale} />
                </div>
                <div>
                  <p className="mb-1 text-xs text-gray-500">{t('investors.portfolio.weight')}</p>
                  <Datum datum={weight} kind="percent" locale={locale} />
                </div>
                <div>
                  <p className="mb-1 text-xs text-gray-500">{t('investors.portfolio.shares')}</p>
                  <Datum datum={row.shares} locale={locale} />
                </div>
                <div>
                  <p className="mb-1 text-xs text-gray-500">
                    {t('investors.portfolio.ownership')}
                  </p>
                  <Datum datum={row.ownership_pct} kind="percent" locale={locale} />
                </div>
              </div>
              {view === "distribucion" &&
              weight.value !== null &&
              Number.isFinite(weight.value) &&
              weight.label !== "SIN_DATOS" ? (
                <div
                  aria-hidden="true"
                  className="h-1.5 overflow-hidden rounded-full bg-gray-900"
                >
                  <div
                    className="h-full rounded-full bg-teal-300/70"
                    style={{
                      width: `${Math.min(100, Math.max(0, weight.value))}%`,
                    }}
                  />
                </div>
              ) : null}
              {row.note ? (
                <p className="text-xs text-gray-500">{row.note}</p>
              ) : null}
            </li>
            );
          })}
        </ul>
      )}
      <Pagination
        basePath={`/inversores/${portfolio.slug}`}
        page={paged.page}
        total={paged.total}
        params={{ vista: view }}
      />
      <p className="text-xs text-gray-500">{ownershipLimitations(portfolio.limitations)}</p>
    </section>
  );
}
