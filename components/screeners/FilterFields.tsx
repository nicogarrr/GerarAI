'use client';

import { useId, useState } from 'react';

import { Input } from '@/components/ui/input';
import { METRIC_LABELS } from '@/lib/research/metric-labels';
import type { ScreenCriterion } from '@/lib/actions/research-tools.actions';

const OPERATORS: { value: ScreenCriterion['operator']; label: string }[] = [
  { value: '>=', label: 'Mayor o igual que (≥)' },
  { value: '>', label: 'Mayor que (>)' },
  { value: '<=', label: 'Menor o igual que (≤)' },
  { value: '<', label: 'Menor que (<)' },
  { value: '==', label: 'Igual a (=)' },
  { value: '!=', label: 'Distinto de (≠)' },
];

const COMMON_METRICS = [
  'roic', 'wacc', 'roe', 'roa', 'revenue_growth', 'fcf_margin',
  'net_margin', 'free_cash_flow', 'net_debt', 'market_cap',
];
/** Metrics with data for at least one company; undefined/empty keeps the full static list. */
function suggestedMetrics(availableMetrics: readonly string[] | undefined): readonly string[] {
  if (!availableMetrics || availableMetrics.length === 0) return COMMON_METRICS;
  const covered = COMMON_METRICS.filter((key) => availableMetrics.includes(key));
  return covered.length > 0 ? covered : COMMON_METRICS;
}

const selectClasses = 'min-h-11 w-full min-w-0 rounded-md border border-gray-700 bg-black px-3 text-sm text-gray-200';
const fieldLabel = 'mb-1.5 block text-sm font-medium text-gray-200';

function describe(expression: string): string {
  const trimmed = expression.trim();
  return METRIC_LABELS[trimmed] ? `${METRIC_LABELS[trimmed]} (${trimmed})` : trimmed;
}

/** The value posted is always the backend's formula/key, never a translated label. */
export function FormulaField({ name, title, hint, initial = '', required = false, availableMetrics }: {
  name: string; title: string; hint: string; initial?: string; required?: boolean;
  availableMetrics?: readonly string[];
}) {
  const id = useId();
  const options = suggestedMetrics(availableMetrics);
  return <div className="min-w-0">
    <label className={fieldLabel} htmlFor={id}>{title}{required ? ' *' : ''}</label>
    <Input autoComplete="off" className="min-h-11" defaultValue={initial} id={id} list={`${id}-metrics`} name={name} placeholder="Elige una métrica o escribe una fórmula" required={required} />
    <datalist id={`${id}-metrics`}>{options.map((key) => <option key={key} label={METRIC_LABELS[key] ?? key} value={key} />)}</datalist>
    <p className="mt-1 text-xs leading-5 text-gray-500">{hint}</p>
  </div>;
}

export function CriterionFields({ suffix = '', initialLeft = '', initialRight = '', initialOperator = '>=', required = false, number = 1, availableMetrics }: {
  suffix?: string; initialLeft?: string; initialRight?: string;
  initialOperator?: ScreenCriterion['operator']; required?: boolean; number?: number;
  availableMetrics?: readonly string[];
}) {
  const [left, setLeft] = useState(initialLeft);
  const [right, setRight] = useState(initialRight);
  const [operator, setOperator] = useState(initialOperator);
  const id = useId();
  const options = suggestedMetrics(availableMetrics);
  const optional = !required;
  return <fieldset className="min-w-0 rounded-lg border border-gray-800 bg-black/20 p-3 sm:p-4">
    <legend className="px-1 text-sm font-semibold text-gray-100">{number === 1 ? 'Condición principal' : `Condición ${number} (opcional)`}</legend>
    <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(150px,190px)_minmax(0,1fr)]">
      <div className="min-w-0"><label className={fieldLabel} htmlFor={`${id}-left`}>Métrica o fórmula{required ? ' *' : ''}</label>
        <Input autoComplete="off" className="min-h-11" defaultValue={initialLeft} id={`${id}-left`} list={`${id}-metrics`} name={`left${suffix}`} onChange={(event) => setLeft(event.target.value)} placeholder="Ej.: roic" required={required} />
        <datalist id={`${id}-metrics`}>{options.map((key) => <option key={key} label={METRIC_LABELS[key] ?? key} value={key} />)}</datalist>
      </div>
      <div><label className={fieldLabel} htmlFor={`${id}-operator`}>Comparación</label>
        <select className={selectClasses} defaultValue={initialOperator} id={`${id}-operator`} name={`operator${suffix}`} onChange={(event) => setOperator(event.target.value as ScreenCriterion['operator'])}>{OPERATORS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}</select>
      </div>
      <div className="min-w-0"><label className={fieldLabel} htmlFor={`${id}-right`}>Valor u otra métrica{required ? ' *' : ''}</label>
        <Input autoComplete="off" className="min-h-11" defaultValue={initialRight} id={`${id}-right`} list={`${id}-metrics-right`} name={`right${suffix}`} onChange={(event) => setRight(event.target.value)} placeholder="Ej.: roa o 0" required={required} />
        <datalist id={`${id}-metrics-right`}>{options.map((key) => <option key={key} label={METRIC_LABELS[key] ?? key} value={key} />)}</datalist>
      </div>
    </div>
    <p aria-live="polite" className="mt-3 rounded-md border border-gray-800 bg-surface-2 px-3 py-2 text-sm leading-6 text-gray-300">
      {left.trim() && right.trim() ? <><span className="text-gray-500">Vista previa: </span>{describe(left)} {operator} {describe(right)}</> :
        optional ? 'Deja ambos campos vacíos para no añadir esta condición.' : 'Elige una métrica y un valor para ver la condición.'}
    </p>
    {number === 1 ? <p className="mt-2 text-xs text-gray-500">Puedes comparar métricas entre sí (roic ≥ roa) o con un número. Las fórmulas admiten +, -, *, /, min, max y abs.</p> : null}
  </fieldset>;
}

export function RankingFields({ initialFormula = '', initialDirection = 'desc', availableMetrics }: { initialFormula?: string; initialDirection?: string; availableMetrics?: readonly string[] }) {
  const id = useId();
  return <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(150px,190px)]">
    <FormulaField availableMetrics={availableMetrics} hint="Opcional: ordena las coincidencias por esta métrica o fórmula." initial={initialFormula} name="ranking" title="Ordenar por" />
    <div><label className={fieldLabel} htmlFor={id}>Dirección del orden</label><select className={selectClasses} defaultValue={initialDirection} id={id} name="direction"><option value="desc">Mayor primero</option><option value="asc">Menor primero</option></select></div>
  </div>;
}

export function CustomMetricFields() {
  const [key, setKey] = useState('');
  const [formula, setFormula] = useState('');
  const id = useId();
  return <div className="space-y-3">
    <p className="text-sm text-gray-400">Define una métrica reutilizable. El identificador se usa en las fórmulas; el nombre se muestra en pantalla.</p>
    <div className="grid gap-3 sm:grid-cols-2">
      <div><label className={fieldLabel} htmlFor={`${id}-name`}>Nombre visible *</label><Input className="min-h-11" id={`${id}-name`} name="name" placeholder="Diferencial ROIC" required /></div>
      <div><label className={fieldLabel} htmlFor={`${id}-key`}>Identificador para fórmulas *</label><Input className="min-h-11" id={`${id}-key`} name="metric_key" onChange={(event) => setKey(event.target.value)} pattern="[a-z][a-z0-9_]+" placeholder="roic_spread" required /><p className="mt-1 text-xs text-gray-500">Minúsculas, números y guiones bajos.</p></div>
    </div>
    <div><label className={fieldLabel} htmlFor={`${id}-formula`}>Cálculo *</label><Input className="min-h-11" id={`${id}-formula`} name="formula" onChange={(event) => setFormula(event.target.value)} placeholder="roic - roa" required /><p className="mt-1 text-xs text-gray-500">Usa claves de métricas, números y operaciones aritméticas; no se ejecuta código.</p></div>
    <p aria-live="polite" className="rounded-md border border-gray-800 bg-surface-2 px-3 py-2 text-sm text-gray-300">Vista previa: {key || 'identificador'} = {formula || 'fórmula'}</p>
    <div className="grid gap-3 sm:grid-cols-2"><div><label className={fieldLabel} htmlFor={`${id}-unit`}>Unidad</label><select className={selectClasses} defaultValue="decimal" id={`${id}-unit`} name="unit"><option value="decimal">Decimal (ej.: 0,12)</option><option value="percent">Porcentaje</option><option value="USD">Importe en USD</option><option value="ratio">Ratio</option></select></div><div><label className={fieldLabel} htmlFor={`${id}-description`}>Definición (opcional)</label><Input className="min-h-11" id={`${id}-description`} name="description" placeholder="Qué mide y cómo interpretarlo" /></div></div>
  </div>;
}
