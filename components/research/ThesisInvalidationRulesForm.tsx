'use client';

import { useState } from 'react';
import { saveThesisInvalidationRules } from '@/lib/actions/research.actions';
import { Button } from '@/components/ui/button';
import {
  CUSTOM_METRIC_PREFIX,
  INVALIDATION_METRICS,
  INVALIDATION_OPERATORS,
  describeInvalidationRule,
  parseThreshold,
  type InvalidationOperator,
  type ThesisInvalidationRule,
} from '@/lib/research/thesis-invalidation-rules';

/**
 * Criterios de invalidación MEDIBLES de la tesis. Cada criterio guardado lo
 * vigila el evaluador de alertas: cuando se cumple, llega un aviso (en la app
 * y por Telegram si está configurado). Se conservan al regenerar la tesis.
 */
export default function ThesisInvalidationRulesForm({
  ticker,
  initialRules,
}: {
  ticker: string;
  initialRules: ThesisInvalidationRule[];
}) {
  const [rules, setRules] = useState<ThesisInvalidationRule[]>(initialRules);
  const [metric, setMetric] = useState<string>(INVALIDATION_METRICS[1].value);
  const [customMetric, setCustomMetric] = useState('');
  const [operator, setOperator] = useState<InvalidationOperator>('<');
  const [threshold, setThreshold] = useState('');
  const [description, setDescription] = useState('');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const persist = async (next: ThesisInvalidationRule[]) => {
    if (pending) return;
    setPending(true);
    setError(null);
    setMessage(null);
    const result = await saveThesisInvalidationRules(ticker, next);
    setPending(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setRules(next);
    setMessage(
      result.count === 0
        ? 'Sin criterios medibles: no se vigila nada.'
        : `Guardado. ${result.count === 1 ? 'Se vigila 1 criterio' : `Se vigilan ${result.count} criterios`} en cada pasada de alertas.`,
    );
  };

  const add = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = parseThreshold(threshold);
    if (value === null) {
      setError('El umbral debe ser un número (admite coma decimal).');
      return;
    }
    const fullMetric = metric === CUSTOM_METRIC_PREFIX ? `${CUSTOM_METRIC_PREFIX}${customMetric.trim()}` : metric;
    if (fullMetric === CUSTOM_METRIC_PREFIX) {
      setError('Escribe el nombre de la métrica financiera.');
      return;
    }
    const rule: ThesisInvalidationRule = {
      metric: fullMetric,
      operator,
      threshold: value,
      description: description.trim() || null,
    };
    await persist([...rules, rule]);
    setThreshold('');
    setDescription('');
  };

  const remove = (index: number) => persist(rules.filter((_, i) => i !== index));

  const selected = INVALIDATION_METRICS.find((item) => item.value === metric);
  const inputClass = 'mt-1 min-h-[44px] w-full rounded border border-gray-700 bg-gray-950 px-2 py-1.5 text-base text-gray-100 sm:min-h-0 sm:text-sm';

  return (
    <div className="mt-3 border-t border-red-900/40 pt-3">
      <h4 className="text-xs font-semibold text-red-200">Criterios medibles con aviso</h4>
      {rules.length > 0 ? (
        <ul className="mt-2 space-y-1.5 text-sm text-gray-300">
          {rules.map((rule, index) => (
            <li key={`${rule.metric}-${rule.operator}-${rule.threshold}-${index}`} className="flex items-start justify-between gap-2">
              <span>
                <span className="font-mono text-xs text-red-200">{describeInvalidationRule(rule)}</span>
                {rule.description ? <span className="text-gray-400"> · {rule.description}</span> : null}
              </span>
              <button
                type="button"
                onClick={() => remove(index)}
                disabled={pending}
                className="shrink-0 text-xs text-gray-500 underline hover:text-red-300 disabled:opacity-50"
                aria-label={`Quitar criterio ${describeInvalidationRule(rule)}`}
              >
                Quitar
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-gray-500">
          Ninguno todavía. Añade uno y te aviso cuando se cumpla.
        </p>
      )}
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-red-300">Añadir criterio medible</summary>
        <form onSubmit={add} className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <label className="col-span-2 text-xs text-gray-300 sm:col-span-1">Métrica
            <select value={metric} onChange={(e) => setMetric(e.target.value)} className={inputClass}>
              {INVALIDATION_METRICS.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
          {metric === CUSTOM_METRIC_PREFIX ? (
            <label className="col-span-2 text-xs text-gray-300 sm:col-span-1">Nombre
              <input value={customMetric} onChange={(e) => setCustomMetric(e.target.value)} maxLength={120} placeholder="roic" className={inputClass} />
            </label>
          ) : null}
          <label className="text-xs text-gray-300">Operador
            <select value={operator} onChange={(e) => setOperator(e.target.value as InvalidationOperator)} className={inputClass}>
              {INVALIDATION_OPERATORS.map((item) => (
                <option key={item.value} value={item.value}>{item.label}</option>
              ))}
            </select>
          </label>
          <label className="text-xs text-gray-300">Umbral
            <input value={threshold} onChange={(e) => setThreshold(e.target.value)} inputMode="decimal" required placeholder="-10" className={inputClass} />
          </label>
          <label className="col-span-2 text-xs text-gray-300 sm:col-span-4">Descripción (opcional)
            <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} placeholder="La acción cotiza por encima del valor esperado" className={inputClass} />
          </label>
          {selected ? <p className="col-span-2 text-xs leading-5 text-gray-500 sm:col-span-4">{selected.hint}</p> : null}
          <div className="col-span-2 sm:col-span-4">
            <Button type="submit" size="sm" disabled={pending}>{pending ? 'Guardando…' : 'Guardar criterio'}</Button>
          </div>
        </form>
      </details>
      {message ? <p className="mt-2 text-xs text-teal-300" role="status">{message}</p> : null}
      {error ? <p className="mt-2 text-xs text-red-300" role="alert">{error}</p> : null}
    </div>
  );
}
