'use client';

import { useState } from 'react';
import { parseLocalizedNumberDetailed } from '@/lib/format';
import { submitThesisHumanInput } from '@/lib/actions/research.actions';
import { Button } from '@/components/ui/button';
import { useLocale, useT } from '@/lib/i18n/client';

export default function ThesisHumanInputForm({ ticker }: { ticker: string }) {
  const t = useT();
  const locale = useLocale();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    setMessage(null);
    try {
      const formData = new FormData(event.currentTarget);
      // El valor llega en el formato del idioma (es-ES «1.234,56», en «1,234.56»): se valida en
      // cliente con el parser compartido y se envía canónico (punto). Los
      // ambiguos («1,234») se rechazan enseñando el formato, nunca se reinterpretan.
      const parsedValue = parseLocalizedNumberDetailed(String(formData.get('value') ?? ''), locale);
      if (!parsedValue.ok) {
        setError(parsedValue.error === 'ambiguous'
          ? t('research.thesisHumanInput.ambiguous')
          : t('research.thesisHumanInput.invalid'));
        setPending(false);
        return;
      }
      formData.set('value', String(parsedValue.value));
      await submitThesisHumanInput(ticker, formData);
      setMessage(t('research.thesisHumanInput.saved'));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : t('research.thesisHumanInput.saveFailed'));
    } finally {
      setPending(false);
    }
  };

  const inputClass = 'mt-1 min-h-[44px] w-full rounded border border-gray-700 bg-gray-950 px-3 py-2 text-base text-gray-100 sm:min-h-0 sm:text-sm';

  return (
    <details className="rounded-lg border border-gray-800 p-4">
      <summary className="cursor-pointer text-sm font-semibold text-gray-200">{t('research.thesisHumanInput.summary')}</summary>
      <p className="mt-2 text-xs leading-5 text-gray-400">
        {t('research.thesisHumanInput.intro')}
      </p>
      <form onSubmit={submit} className="mt-3 space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs text-gray-300">{t('research.thesisHumanInput.driverKey')}
            <input name="driver_key" required maxLength={160} className={inputClass} placeholder="revenue" />
          </label>
          <label className="text-xs text-gray-300">{t('research.thesisHumanInput.fiscalYear')}
            <input name="fiscal_year" type="number" required min={1900} max={2200} step={1} className={inputClass} />
          </label>
          <label className="text-xs text-gray-300">{t('research.thesisHumanInput.scenario')}
            <select name="scenario" defaultValue="base" className={inputClass}>
              <option value="bear">Bear</option><option value="base">Base</option><option value="bull">Bull</option>
            </select>
          </label>
          <label className="text-xs text-gray-300">{t('research.thesisHumanInput.value')}
            {/* type="text" (no "number"): el input numérico rechaza la coma
                decimal es-ES; inputMode conserva el teclado numérico. */}
            <input name="value" type="text" inputMode="decimal" required className={inputClass} />
          </label>
        </div>
        <label className="block text-xs text-gray-300">{t('research.thesisHumanInput.source')}
          <input name="source" required maxLength={240} className={inputClass} />
        </label>
        <label className="block text-xs text-gray-300">{t('research.thesisHumanInput.rationale')}
          <textarea name="rationale" required maxLength={5000} rows={3} className={inputClass} />
        </label>
        <Button type="submit" disabled={pending}>{pending ? t('research.thesisHumanInput.saving') : t('research.thesisHumanInput.save')}</Button>
        {message ? <p role="status" className="text-sm text-teal-300">{message}</p> : null}
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
      </form>
    </details>
  );
}
