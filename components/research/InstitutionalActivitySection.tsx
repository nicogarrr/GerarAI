import { getInstitutionalActivity } from '@/lib/actions/investors.actions';
import type { Locale } from '@/lib/i18n/locale';
import type { ActivityFilter } from '@/lib/research/institutional-holders';
import { InstitutionalActivityTable } from './InstitutionalActivityTable';

/** Server-only section: a single stored-data request, never one per manager. */
export async function InstitutionalActivitySection({ ticker, query, locale }: {
  ticker: string; query: Record<string, string | undefined>; locale: Locale;
}) {
  const status: ActivityFilter = ['aumenta', 'reduce', 'nuevo', 'vende_todo'].includes(query.ia_status ?? '')
    ? query.ia_status as ActivityFilter : 'all';
  const page = /^\d{1,8}$/.test(query.ia_page ?? '') ? Math.max(1, Number(query.ia_page)) : 1;
  const search = new URLSearchParams(Object.entries(query).filter((entry): entry is [string, string] => typeof entry[1] === 'string'));
  const data = await getInstitutionalActivity(ticker, status, page).catch(() => null);
  return <InstitutionalActivityTable baseHref={`/research/${encodeURIComponent(ticker)}?${search}`} data={data} locale={locale} />;
}
