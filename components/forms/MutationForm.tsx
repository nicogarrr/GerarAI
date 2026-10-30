'use client';

import { useRef, useState, type ComponentPropsWithoutRef } from 'react';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { classifyError, getFriendlyErrorMessage, isNextRedirectError } from '@/lib/types/errors';
import { useT } from '@/lib/i18n/client';

type MutationFormProps = Omit<ComponentPropsWithoutRef<'form'>, 'action'> & {
  action: (formData: FormData) => Promise<unknown>;
  successMessage?: string;
  resetOnSuccess?: boolean;
  showSuccessInline?: boolean;
};

export function MutationForm({
  action,
  children,
  successMessage,
  resetOnSuccess = false,
  showSuccessInline = false,
  ...props
}: MutationFormProps) {
  const t = useT();
  const resolvedSuccessMessage = successMessage ?? t('auth.fields.defaultSuccess');
  const formRef = useRef<HTMLFormElement>(null);
  const lastFormData = useRef<FormData | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  async function submit(formData: FormData) {
    if (isPending) return;
    lastFormData.current = formData;
    setError(null);
    setSuccess(null);
    setIsPending(true);
    try {
      const result = await action(formData);
      // Contrato de resultado tipado (carril B, p.ej. createAlertResult /
      // uploadKnowledgeDocumentResult): un { ok: false } es un rechazo de
      // negocio con su mensaje, no un exito: va al error inline y NUNCA al
      // toast de exito. Sin este caso MutationForm celebraba el rechazo.
      if (result && typeof result === 'object' && 'ok' in result && (result as { ok: unknown }).ok === false) {
        const message =
          'message' in result && typeof (result as { message: unknown }).message === 'string'
            ? (result as { message: string }).message
            : t('errors.mutationFailed');
        setError(message);
        return;
      }
      const message = result && typeof result === 'object' && 'message' in result && typeof result.message === 'string' ? result.message : resolvedSuccessMessage;
      if (resetOnSuccess) formRef.current?.reset();
      toast.success(message);
      if (showSuccessInline) setSuccess(message);
    } catch (err) {
      // Los redirects de Next forman parte de la navegación: re-lanzarlos.
      if (isNextRedirectError(err)) throw err;
      // Error inline siempre visible: ningún submit falla en silencio.
      setError(getFriendlyErrorMessage(err));
      // Toast SOLO cuando aporta una acción (B7): motor caído -> "Reintentar"
      // con los mismos datos; versión obsoleta -> "Recargar"; duplicado ->
      // aviso informativo. Para el resto de causas el toast repetía el
      // mensaje inline sin añadir nada.
      const cause = classifyError(err);
      if (cause === 'offline' || cause === 'stale' || cause === 'duplicate') {
        showErrorToast(err, {
          onRetry: async () => {
            const payload = lastFormData.current;
            if (payload) await submit(payload);
          },
          successMessage: resolvedSuccessMessage,
        });
      }
    } finally {
      setIsPending(false);
    }
  }

  return (
    <form {...props} action={submit} aria-busy={isPending} ref={formRef}>
      {isPending ? (
        <span aria-live="polite" role="status" className="sr-only">
          {t('auth.fields.submitting')}
        </span>
      ) : null}
      <fieldset disabled={isPending} className="contents">
        {children}
      </fieldset>
      {success ? <p className="mt-3 text-sm text-teal-300" role="status">{success}</p> : null}
      {error ? (
        <p className="mt-3 text-sm text-red-300" role="alert">
          {error}
        </p>
      ) : null}
    </form>
  );
}
