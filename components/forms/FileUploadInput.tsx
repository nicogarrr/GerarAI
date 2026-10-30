'use client';

import { useEffect, useRef, useState, type ChangeEvent, type ComponentPropsWithoutRef } from 'react';
import { toast } from 'sonner';
import { useT } from '@/lib/i18n/client';
import { formatNumber } from '@/lib/format';
import { cn } from '@/lib/utils';

// Límite real de subida: next.config.ts → experimental.serverActions.bodySizeLimit = 4mb.
// Vercel Hobby corta el body de las server actions en ~4.5 MB, así que un archivo
// mayor falla siempre: se avisa al elegirlo y se bloquea el envío del formulario
// (botones de submit deshabilitados + submit interceptado + validación nativa).
export const MAX_UPLOAD_MB = 4;

type FileUploadInputProps = Omit<ComponentPropsWithoutRef<'input'>, 'type' | 'onChange'> & {
  maxMB?: number;
};

export function FileUploadInput({ maxMB = MAX_UPLOAD_MB, className, id, name, ...props }: FileUploadInputProps) {
  const t = useT();
  const rootRef = useRef<HTMLDivElement>(null);
  const [warning, setWarning] = useState<string | null>(null);
  // F142: el texto del input file nativo («Choose File / No file chosen»)
  // lo fija el idioma del NAVEGADOR, no el de la app - en una interfaz
  // española se veía en inglés. El control real queda sr-only y el
  // disparador visible es nuestro, en español, con el nombre del archivo.
  const [fileName, setFileName] = useState<string | null>(null);
  const tooBig = warning !== null;
  const inputId = id ?? name ?? 'file-upload';
  const warningId = `${inputId}-limite`;

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    setFileName(file?.name ?? null);
    if (!file) {
      setWarning(null);
      event.target.setCustomValidity('');
      return;
    }
    const limitBytes = maxMB * 1024 * 1024;
    if (file.size > limitBytes) {
      const sizeMb = formatNumber(file.size / (1024 * 1024), {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      });
      const message = t('errors.upload.tooBig', { name: file.name, sizeMb, maxMB });
      setWarning(message);
      event.target.setCustomValidity(message);
      toast.warning(message);
    } else {
      setWarning(null);
      event.target.setCustomValidity('');
    }
  }

  // Bloquea el envío del formulario padre mientras el archivo supere el límite:
  // deshabilita sus botones de submit (marcados con data-upload-blocked para no
  // tocar los deshabilitados por otros motivos) e intercepta el submit
  // (cubre el envío con tecla Enter, que no pasa por el botón).
  useEffect(() => {
    const form = rootRef.current?.querySelector('input[type="file"]')?.closest('form');
    if (!form) return;
    const submits = Array.from(
      form.querySelectorAll<HTMLButtonElement | HTMLInputElement>(
        'button[type="submit"], input[type="submit"]'
      )
    );
    submits.forEach((el) => {
      if (tooBig) {
        if (!el.disabled) {
          el.disabled = true;
          el.dataset.uploadBlocked = '1';
        }
        el.setAttribute('aria-disabled', 'true');
      } else {
        if (el.dataset.uploadBlocked === '1') {
          el.disabled = false;
          delete el.dataset.uploadBlocked;
        }
        el.removeAttribute('aria-disabled');
      }
    });
    const onSubmit = (event: Event) => {
      if (tooBig) {
        event.preventDefault();
        event.stopPropagation();
        if (warning) toast.warning(warning);
      }
    };
    // F142: un reset del formulario padre (p. ej. MutationForm tras una
    // subida exitosa) limpia el input nativo pero NO el estado de React -
    // sin esto, el nombre del archivo anterior quedaba en pantalla sin
    // archivo seleccionado. El state se sincroniza con el reset.
    const onReset = () => {
      setFileName(null);
      setWarning(null);
      rootRef.current
        ?.querySelector<HTMLInputElement>('input[type="file"]')
        ?.setCustomValidity('');
    };
    form.addEventListener('submit', onSubmit, true);
    form.addEventListener('reset', onReset);
    return () => {
      form.removeEventListener('submit', onSubmit, true);
      form.removeEventListener('reset', onReset);
      submits.forEach((el) => {
        if (el.dataset.uploadBlocked === '1') {
          el.disabled = false;
          delete el.dataset.uploadBlocked;
        }
        el.removeAttribute('aria-disabled');
      });
    };
  }, [tooBig, warning]);

  return (
    <div ref={rootRef} className={cn('w-full', className)}>
      {/* <input> nativo a propósito: ui/Input impone w-full/h-10/borde en la
          base y, con sr-only, el width:100% ganaba a width:1px (sr-only se
          ordena antes en el stylesheet), dejando una caja invisible al 100%
          que desbordaba en /research?view=documents y /knowledge?tab=subir
          (F303). */}
      <input
        {...props}
        id={inputId}
        name={name}
        type="file"
        aria-invalid={tooBig}
        aria-describedby={warningId}
        className="sr-only"
        onChange={handleChange}
      />
      <div className="flex min-h-[44px] items-center gap-3">
        <label
          htmlFor={inputId}
          className={cn(
            'inline-flex cursor-pointer items-center rounded-md border border-gray-700 bg-gray-900 px-3 py-2 text-sm font-medium text-gray-200 hover:border-gray-500 hover:text-white',
            warning ? 'border-red-500' : null,
          )}
        >
          {t('errors.upload.choose')}
        </label>
        <span className="truncate text-sm text-gray-400">{fileName ?? t('errors.upload.noFile')}</span>
      </div>
      {warning ? (
        <p id={warningId} role="alert" className="mt-1 text-xs text-red-400">
          {warning} El envío está bloqueado hasta que elijas un archivo válido.
        </p>
      ) : (
        <p id={warningId} className="mt-1 text-xs text-gray-500">
          Máximo {maxMB} MB.
        </p>
      )}
    </div>
  );
}
