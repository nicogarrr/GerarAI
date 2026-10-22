'use client';

import { useRef, useState, type ComponentPropsWithoutRef } from 'react';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { classifyError, getFriendlyErrorMessage, isNextRedirectError } from '@/lib/types/errors';

type MutationFormProps = Omit<ComponentPropsWithoutRef<'form'>, 'action'> & {
  action: (formData: FormData) => Promise<unknown>;
  successMessage?: string;
  resetOnSuccess?: boolean;
  showSuccessInline?: boolean;
  /** Tras un error, restaura los valores escritos (React resetea los campos
   *  no controlados al completar la acción). Opt-in: no cambia otros forms. */
  preserveOnError?: boolean;
};

export function MutationForm({
  action,
  children,
  successMessage = 'Operación completada',
  resetOnSuccess = false,
  showSuccessInline = false,
  preserveOnError = false,
  ...props
}: MutationFormProps) {
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
    // Restaura los valores escritos tras un fallo (React resetea los campos
    // no controlados al completar la acción; el timeout queda después).
    const restoreInputs = () => {
      if (!preserveOnError) return;
      const form = formRef.current;
      const data = lastFormData.current;
      if (!form || !data) return;
      // Doble rAF: queda DESPUÉS del commit de React que resetea el form.
      requestAnimationFrame(() => requestAnimationFrame(() => {
        for (const [name, value] of data.entries()) {
          const field = form.elements.namedItem(name);
          if (field instanceof HTMLInputElement && field.type === 'checkbox') {
            field.checked = value === 'on';
          } else if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement) {
            if (typeof value === 'string') field.value = value;
          }
        }
      }));
    };
    try {
      const result = await action(formData);
      // Resultado tipado de error esperado (p. ej. 422 del contrato): inline,
      // con los datos conservados. No es un éxito ni un fallo inesperado.
      if (result && typeof result === 'object' && (result as { ok?: unknown }).ok === false && typeof (result as { message?: unknown }).message === 'string') {
        restoreInputs();
        setError((result as { message: string }).message);
        return;
      }
      const message = result && typeof result === 'object' && 'message' in result && typeof result.message === 'string' ? result.message : successMessage;
      const tone = result && typeof result === 'object' && 'tone' in result ? (result as { tone?: string }).tone : undefined;
      if (resetOnSuccess) formRef.current?.reset();
      if (tone === 'neutral') toast(message); else toast.success(message);
      if (showSuccessInline) setSuccess(message);
    } catch (err) {
      // Los redirects de Next forman parte de la navegación: re-lanzarlos.
      if (isNextRedirectError(err)) throw err;
      restoreInputs();
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
          successMessage,
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
          Enviando formulario
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
