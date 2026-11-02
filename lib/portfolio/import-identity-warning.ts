import type { TranslateFn } from '@/lib/i18n/translate';
import { t } from '@/lib/i18n/t';

/**
 * Aviso de CSV sin identificador de operación (ibkr_import_service.py,
 * identity_warning): el backend lo manda solo en castellano. Se muestra con la
 * clave del catálogo en el idioma activo; un aviso distinto pasa tal cual.
 */
const CSV_WITHOUT_ID_PREFIX = 'CSV sin identificador de operación:';

export function identityWarningText(warning: string, ti: TranslateFn = t): string {
    return warning.startsWith(CSV_WITHOUT_ID_PREFIX) ? ti('portfolio.importIbk.identityWarning') : warning;
}
