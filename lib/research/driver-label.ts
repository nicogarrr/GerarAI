import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

export function driverLabel(key: string, locale: Locale = DEFAULT_LOCALE): string {
    const t = createTranslator(locale);
    const labels: Record<string, string> = {
        growth: t('research.driverLabels.growth'),
        revenue_growth: t('research.driverLabels.revenue_growth'),
        margin: t('research.driverLabels.margin'),
        gross_margin: t('research.driverLabels.gross_margin'),
        operating_margin: t('research.driverLabels.operating_margin'),
        ebit_margin: t('research.driverLabels.ebit_margin'),
        fcf: t('research.driverLabels.fcf'),
        fcf_margin: t('research.driverLabels.fcf_margin'),
        wacc: t('research.driverLabels.wacc'),
        tax_rate: t('research.driverLabels.tax_rate'),
        capex: t('research.driverLabels.capex'),
        terminal_growth: t('research.driverLabels.terminal_growth'),
        buyback: t('research.driverLabels.buyback'),
        dilution: t('research.driverLabels.dilution'),
    };
    return Object.hasOwn(labels, key) ? labels[key] : key.replaceAll('_', ' ');
}
