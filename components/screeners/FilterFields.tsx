'use client';

import { useId, useMemo, useState } from 'react';
import { useCommandState } from 'cmdk';
import { Check, ChevronsUpDown, X } from 'lucide-react';

import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { METRIC_LABELS, metricLabel } from '@/lib/research/metric-labels';
import { useLocale, useT } from '@/lib/i18n/client';
import { UNITS, buildMetricOptions, metricGroupLabel, fromBackendValue, shownValueError, toBackendValue, type MetricOption, type UnitKind } from '@/lib/screener-metrics';
import type { CustomMetric, ScreenCriterion } from '@/lib/actions/research-tools.actions';

type CustomMetricInfo = Pick<CustomMetric, 'metric_key' | 'name' | 'unit'>;

const OPERATORS = [
  { value: '>=', symbol: '≥', key: 'gte' },
  { value: '>', symbol: '>', key: 'gt' },
  { value: '<=', symbol: '≤', key: 'lte' },
  { value: '<', symbol: '<', key: 'lt' },
  { value: '==', symbol: '=', key: 'eq' },
  { value: '!=', symbol: '≠', key: 'ne' },
] as const satisfies readonly { value: ScreenCriterion['operator']; symbol: string; key: string }[];

/** Nota de cobertura vacia conocida: solo sin busqueda activa, para no
 *  acumularse con el «Sin resultados» del filtro. Lee el valor real de
 *  cmdk (sin estado paralelo que se desincronice). */
function EmptyCoverageNote() {
  const search = useCommandState((state) => state.search);
  const t = useT();
  if (search.trim() !== '') return null;
  return <p className="px-3 py-2 text-sm text-gray-400">{t('screener.noMetricsAvailable')}</p>;
}

const selectClasses = 'min-h-11 w-full min-w-0 rounded-md border border-gray-700 bg-black px-3 text-base text-gray-200 sm:text-sm';
const fieldLabel = 'mb-1.5 block text-sm font-medium text-gray-200';

function describe(expression: string, locale: 'es' | 'en'): string {
  const trimmed = expression.trim();
  return METRIC_LABELS[trimmed] ? `${metricLabel(trimmed, locale)} (${trimmed})` : trimmed;
}

function unitOf(key: string, options: readonly MetricOption[]): UnitKind {
  return options.find((option) => option.key === key.trim())?.unit ?? 'number';
}

/**
 * Selector de métrica con búsqueda y grupos. Lo que se manda es siempre la
 * clave del backend; la fórmula libre queda como modo avanzado dentro del
 * propio selector.
 */
function MetricPicker({ id, name, value, onChange, options, placeholder, required = false, clearable = false }: {
  id: string; name: string; value: string; onChange: (next: string) => void;
  options: readonly MetricOption[]; placeholder: string; required?: boolean; clearable?: boolean;
}) {
  const t = useT();
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [formula, setFormula] = useState(() => value.trim() !== '' && !options.some((option) => option.key === value.trim()));
  const selected = options.find((option) => option.key === value.trim());
  const groups = useMemo(() => {
    const map = new Map<string, MetricOption[]>();
    for (const option of options) map.set(option.group, [...(map.get(option.group) ?? []), option]);
    return [...map.entries()];
  }, [options]);

  if (formula) {
    return <div className="flex min-w-0 gap-2">
      <Input autoComplete="off" className="min-h-11" id={id} name={name} onChange={(event) => onChange(event.target.value)} placeholder="roic - roa" required={required} value={value} />
      <Button aria-label={t('screener.backToMetricList')} className="h-11 shrink-0" onClick={() => { setFormula(false); onChange(''); }} type="button" variant="outline"><X aria-hidden="true" className="h-4 w-4" /></Button>
    </div>;
  }

  return <div className="min-w-0">
    <input aria-hidden="true" className="sr-only" name={name} onChange={() => undefined} readOnly required={required} tabIndex={-1} value={value} />
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <Button aria-controls={`${id}-list`} aria-expanded={open} className="h-11 w-full justify-between border-gray-700 bg-black px-3 text-sm font-normal text-gray-200 hover:bg-gray-900" id={id} role="combobox" type="button" variant="outline">
          <span className={cn('truncate', !selected && 'text-gray-500')}>{selected ? selected.label : placeholder}</span>
          <ChevronsUpDown aria-hidden="true" className="ml-2 h-4 w-4 shrink-0 text-gray-500" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(92vw,22rem)] p-0">
        <Command>
          <CommandInput placeholder={t('screener.searchMetric')} />
          <CommandList className="max-h-72" id={`${id}-list`}>
            <CommandEmpty>{t('common.states.noResults')}</CommandEmpty>
            {options.length === 0 ? <EmptyCoverageNote /> : null}
            {groups.map(([title, items]) => <CommandGroup heading={metricGroupLabel(title, locale)} key={title}>
              {items.map((option) => <CommandItem key={option.key} onSelect={() => { onChange(option.key); setOpen(false); }} value={`${option.label} ${option.key}`}>
                <Check aria-hidden="true" className={cn('mr-2 h-4 w-4', selected?.key === option.key ? 'opacity-100' : 'opacity-0')} />
                <span className="min-w-0 flex-1 truncate">{option.label}</span>
                <span className="ml-2 text-xs text-gray-500">{UNITS[option.unit].suffix}</span>
              </CommandItem>)}
            </CommandGroup>)}
            <CommandGroup heading={t('screener.advanced')}>
              {clearable && value ? <CommandItem onSelect={() => { onChange(''); setOpen(false); }} value="quitar seleccion">{t('screener.clearSelection')}</CommandItem> : null}
              <CommandItem onSelect={() => { setFormula(true); setOpen(false); }} value="formula avanzada">{t('screener.formulaOption')}</CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  </div>;
}

/** Ordenar por: mismo selector, opcional. */
export function FormulaField({ name, title, initial = '', required = false, availableMetrics, customMetrics }: {
  name: string; title: string; hint?: string; initial?: string; required?: boolean;
  availableMetrics?: readonly string[]; customMetrics?: readonly CustomMetricInfo[];
}) {
  const id = useId();
  const t = useT();
  const locale = useLocale();
  const options = useMemo(() => buildMetricOptions(availableMetrics, customMetrics, (key) => metricLabel(key, locale)), [availableMetrics, customMetrics, locale]);
  const [value, setValue] = useState(initial);
  return <div className="min-w-0">
    <label className={fieldLabel} htmlFor={id}>{title}{required ? ' *' : ''}</label>
    <MetricPicker clearable id={id} name={name} onChange={setValue} options={options} placeholder={t('screener.chooseMetric')} required={required} value={value} />
  </div>;
}

export function CriterionFields({ suffix = '', initialLeft = '', initialRight = '', initialOperator = '>=', required = false, number = 1, availableMetrics, customMetrics }: {
  suffix?: string; initialLeft?: string; initialRight?: string;
  initialOperator?: ScreenCriterion['operator']; required?: boolean; number?: number;
  availableMetrics?: readonly string[]; customMetrics?: readonly CustomMetricInfo[];
}) {
  const id = useId();
  const t = useT();
  const locale = useLocale();
  const options = useMemo(() => buildMetricOptions(availableMetrics, customMetrics, (key) => metricLabel(key, locale)), [availableMetrics, customMetrics, locale]);
  const [left, setLeft] = useState(initialLeft);
  const [operator, setOperator] = useState(initialOperator);
  const initialNumeric = initialRight.trim() !== '' && Number.isFinite(Number(initialRight));
  const [rightMode, setRightMode] = useState<'valor' | 'metrica'>(initialRight.trim() !== '' && !initialNumeric ? 'metrica' : 'valor');
  const [shown, setShown] = useState(() => (initialNumeric ? fromBackendValue(initialRight, unitOf(initialLeft, options), locale) : ''));
  const [rightMetric, setRightMetric] = useState(initialNumeric ? '' : initialRight);
  const unit = UNITS[unitOf(left, options)];
  const unitKind = unitOf(left, options);
  const rightValue = rightMode === 'valor' ? toBackendValue(shown, unitKind, locale) : rightMetric;
  const valueError = rightMode === 'valor' ? shownValueError(shown, locale) : null;
  const complete = left.trim() !== '' && rightValue !== '';
  const symbol = OPERATORS.find((op) => op.value === operator)?.symbol ?? operator;
  const preview = rightMode === 'valor' ? `${shown}${unit.suffix ? ` ${unit.suffix}` : ''}` : describe(rightMetric, locale);
  return <fieldset className="min-w-0 rounded-lg border border-gray-800 bg-black/20 p-3 sm:p-4">
    <legend className="px-1 text-sm font-semibold text-gray-100">{number === 1 ? t('screener.condition') : t('screener.conditionN', { number })}</legend>
    <div className="grid min-w-0 gap-3">
      <div className="min-w-0"><label className={fieldLabel} htmlFor={`${id}-left`}>{t('screener.metricLabel')}{required ? ' *' : ''}</label>
        <MetricPicker id={`${id}-left`} name={`left${suffix}`} onChange={setLeft} options={options} placeholder={t('screener.chooseMetric')} required={required} value={left} />
      </div>
      <div role="radiogroup" aria-label={t('screener.comparisonAria')} className="grid grid-cols-6 gap-1 rounded-lg border border-gray-800 p-1">
        {OPERATORS.map(({ value, symbol: sym, key: opKey }) => { const label = t(`screener.operators.${opKey}`); return <label className={cn('flex min-h-11 cursor-pointer items-center justify-center rounded-md text-base transition-colors', operator === value ? 'bg-teal-400/10 text-teal-300' : 'text-gray-400 hover:bg-gray-800')} key={value} title={label}>
          <input aria-label={label} checked={operator === value} className="sr-only" name={`operator${suffix}`} onChange={() => setOperator(value)} type="radio" value={value} />{sym}
        </label>; })}
      </div>
      <div className="min-w-0">
        <div className="mb-1.5 flex items-center justify-between gap-2"><label className="text-sm font-medium text-gray-200" htmlFor={`${id}-right`}>{rightMode === 'valor' ? t('screener.valueLabel') : t('screener.otherMetricLabel')}{required ? ' *' : ''}</label>
          <div role="radiogroup" aria-label={t('screener.comparisonTypeAria')} className="flex rounded-md border border-gray-800 p-0.5 text-xs">
            {([['valor', t('screener.valueLabel')], ['metrica', t('screener.metricLabel')]] as const).map(([mode, text]) => <label className={cn('flex min-h-11 cursor-pointer items-center justify-center rounded px-2.5 py-1.5 sm:min-h-0', rightMode === mode ? 'bg-teal-400/10 text-teal-300' : 'text-gray-400')} key={mode}><input checked={rightMode === mode} className="sr-only" name={`${id}-mode`} onChange={() => setRightMode(mode)} type="radio" value={mode} />{text}</label>)}
          </div>
        </div>
        {rightMode === 'valor' ? <div className="flex items-center gap-2">
          <Input autoComplete="off" className="min-h-11" id={`${id}-right`} inputMode="decimal" onChange={(event) => setShown(event.target.value)} placeholder="0" required={required} type="text" value={shown} />
          {/* type="text" (no "number"): el input numérico rechaza la coma decimal es-ES. */}
          {unit.suffix ? <span className="w-9 shrink-0 text-sm text-gray-400">{unit.suffix}</span> : null}
          <input name={`right${suffix}`} readOnly type="hidden" value={rightValue} />
        </div> : <MetricPicker id={`${id}-right`} name={`right${suffix}`} onChange={setRightMetric} options={options} placeholder={t('screener.chooseMetric')} required={required} value={rightMetric} />}
        {valueError ? <p className="mt-1.5 text-xs text-amber-300" role="alert">{valueError === 'ambiguous'
          ? t('screener.ambiguousNumber')
          : t('screener.invalidNumber')}</p> : null}
      </div>
    </div>
    {complete ? <p aria-live="polite" className="mt-3 rounded-md border border-gray-800 bg-surface-2 px-3 py-2 text-sm text-gray-300">{describe(left, locale)} {symbol} {preview}</p> : null}
  </fieldset>;
}

export function RankingFields({ initialFormula = '', initialDirection = 'desc', availableMetrics, customMetrics }: { initialFormula?: string; initialDirection?: string; availableMetrics?: readonly string[]; customMetrics?: readonly CustomMetricInfo[] }) {
  const t = useT();
  const [direction, setDirection] = useState(initialDirection === 'asc' ? 'asc' : 'desc');
  return <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(150px,190px)]">
    <FormulaField availableMetrics={availableMetrics} customMetrics={customMetrics} initial={initialFormula} name="ranking" title={t('screener.orderBy')} />
    <DirectionToggle name="direction" onChange={setDirection} value={direction} />
  </div>;
}

export function DirectionToggle({ name, value, onChange }: { name: string; value: string; onChange: (next: 'asc' | 'desc') => void }) {
  const t = useT();
  return <div><span className={fieldLabel}>{t('screener.orderLabel')}</span>
    <div role="radiogroup" aria-label={t('screener.orderLabel')} className="grid grid-cols-2 gap-1 rounded-lg border border-gray-800 p-1">
      {([['desc', t('screener.directionDesc')], ['asc', t('screener.directionAsc')]] as const).map(([v, text]) => <label className={cn('flex min-h-11 cursor-pointer items-center justify-center rounded-md px-2 text-center text-xs transition-colors sm:min-h-9', value === v ? 'bg-teal-400/10 text-teal-300' : 'text-gray-400 hover:bg-gray-800')} key={v}>
        <input checked={value === v} className="sr-only" name={name} onChange={() => onChange(v)} type="radio" value={v} />{text}
      </label>)}
    </div>
  </div>;
}

export function CustomMetricFields() {
  const t = useT();
  const [key, setKey] = useState('');
  const [formula, setFormula] = useState('');
  const id = useId();
  return <div className="space-y-3">
    <p className="text-sm text-gray-400">{t('screener.customIntro')}</p>
    <div className="grid gap-3 sm:grid-cols-2">
      <div><label className={fieldLabel} htmlFor={`${id}-name`}>{t('screener.customVisibleName')} *</label><Input className="min-h-11" id={`${id}-name`} name="name" placeholder={t('screener.customVisibleNamePlaceholder')} required /></div>
      <div><label className={fieldLabel} htmlFor={`${id}-key`}>{t('screener.customIdentifier')} *</label><Input className="min-h-11" id={`${id}-key`} name="metric_key" onChange={(event) => setKey(event.target.value)} pattern="[a-z][a-z0-9_]+" placeholder="roic_spread" required /><p className="mt-1 text-xs text-gray-500">{t('screener.customIdentifierHint')}</p></div>
    </div>
    <div><label className={fieldLabel} htmlFor={`${id}-formula`}>{t('screener.customCalc')} *</label><Input className="min-h-11" id={`${id}-formula`} name="formula" onChange={(event) => setFormula(event.target.value)} placeholder="roic - roa" required /><p className="mt-1 text-xs text-gray-500">{t('screener.customCalcHint')}</p></div>
    <p aria-live="polite" className="rounded-md border border-gray-800 bg-surface-2 px-3 py-2 text-sm text-gray-300">{t('screener.customPreview', { key: key || t('screener.customPreviewKeyFallback'), formula: formula || t('screener.customPreviewFormulaFallback') })}</p>
    <div className="grid gap-3 sm:grid-cols-2"><div><label className={fieldLabel} htmlFor={`${id}-unit`}>{t('screener.customUnit')}</label><select className={selectClasses} defaultValue="decimal" id={`${id}-unit`} name="unit"><option value="decimal">{t('screener.unitDecimal')}</option><option value="percent">{t('screener.unitPercent')}</option><option value="USD">{t('screener.unitUsd')}</option><option value="ratio">{t('screener.unitRatio')}</option></select></div><div><label className={fieldLabel} htmlFor={`${id}-description`}>{t('screener.customDefinition')}</label><Input className="min-h-11" id={`${id}-description`} name="description" placeholder={t('screener.customDefinitionPlaceholder')} /></div></div>
  </div>;
}
