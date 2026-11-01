/**
 * Toasts de error accionables para componentes de cliente.
 *
 * Clasifica la causa del error (motor caído, duplicado, validación...) con
 * `classifyError` y traduce el mensaje con `getFriendlyErrorMessage`; cuando
 * el fallo es recuperable añade la acción "Reintentar" al toast.
 */
import { toast } from 'sonner';
import {
  classifyError,
  getFriendlyErrorMessage,
  type ErrorCause,
} from '@/lib/types/errors';
import { documentLocale, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

export interface ErrorToastOptions {
  /** Se ejecuta con el botón "Reintentar" (causa `offline`) */
  onRetry?: () => void | Promise<void>;
  /** Mensaje específico para el caso "ya existe / duplicado" */
  duplicateMessage?: string;
  /** Toast de éxito a mostrar cuando el reintento funciona */
  successMessage?: string;
  /** Idioma del aviso; por defecto, el de la página (`<html lang>`). */
  locale?: Locale;
}

export function showErrorToast(error: unknown, options: ErrorToastOptions = {}): ErrorCause {
  const cause = classifyError(error);
  const locale = options.locale ?? documentLocale();
  const t = createTranslator(locale);
  const message = getFriendlyErrorMessage(error, {
    duplicateMessage: options.duplicateMessage,
    locale,
  });

  if (cause === 'duplicate') {
    toast.info(message);
    return cause;
  }

  if (cause === 'stale') {
    toast.error(message, {
      action: {
        label: t('errors.friendly.reload'),
        onClick: () => window.location.reload(),
      },
    });
    return cause;
  }

  const retry =
    cause === 'offline' && options.onRetry
      ? {
          label: t('common.actions.retry'),
          onClick: () => {
            void Promise.resolve()
              .then(() => options.onRetry?.())
              .then(() => {
                if (options.successMessage) toast.success(options.successMessage);
              })
              .catch((error: unknown) => {
                showErrorToast(error, options);
              });
          },
        }
      : undefined;

  toast.error(message, retry ? { action: retry } : undefined);
  return cause;
}
