'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { Filter, X } from 'lucide-react';
import { etiquetaSector } from '@/lib/labels';

export interface ProPicksFilters {
  timePeriod: 'week' | 'month' | 'quarter' | 'year';
  limit: number;
  minScore: number;
  sector: string;
  sortBy: 'score' | 'momentum' | 'value' | 'growth' | 'profitability';
}

interface Props {
  filters: ProPicksFilters;
  disabled?: boolean;
  /** Categorías neutras en TODOS los picks del run (F184): ordenar por
      ellas es ordenar por una constante — la opción se deshabilita. */
  neutralSorts?: ReadonlyArray<'momentum' | 'value'>;
  onFiltersChange: (filters: ProPicksFilters) => void;
  onApply: () => void;
}

// Los `value` siguen en inglés: es lo que espera el backend. Lo que se
// muestra es la etiqueta española de lib/labels.ts (mapa compartido con el
// Screener, que antes llevaba su propia lista).
const sectors = [
  'all',
  'Technology',
  'Healthcare',
  'Financial Services',
  'Consumer Discretionary',
  'Industrials',
  'Consumer Staples',
  'Energy',
  'Utilities',
  'Real Estate',
  'Materials',
  'Communication Services'
];

export default function EnhancedProPicksFilters({ filters, disabled = false, neutralSorts = [], onFiltersChange, onApply }: Props) {
  const updateFilter = <K extends keyof ProPicksFilters>(key: K, value: ProPicksFilters[K]) => {
    onFiltersChange({ ...filters, [key]: value });
  };

  const resetFilters = () => {
    onFiltersChange({
      timePeriod: 'month',
      limit: 20,
      minScore: 70,
      sector: 'all',
      sortBy: 'score',
    });
  };

  return (
    <Card className="w-full min-w-0 border-gray-700 bg-gray-800/50">
      <fieldset disabled={disabled} className="contents">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Filter className="h-5 w-5 text-teal-400" />
              <CardTitle className="text-lg">Filtros Avanzados</CardTitle>
            </div>
            <Button variant="ghost" size="sm" className="min-h-[44px]" onClick={resetFilters}>
              <X className="h-4 w-4 mr-1" />
              Limpiar
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Cantidad de Resultados */}
          <div className="space-y-3">
            <Label className="text-sm font-medium text-gray-200">
              Cantidad de Acciones: {filters.limit}
            </Label>
            <Slider
              disabled={disabled}
              value={[filters.limit]}
              onValueChange={(value) => updateFilter('limit', value[0])}
              min={5}
              max={50}
              step={5}
              className="py-3"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>5</span>
              <span>50</span>
            </div>
          </div>

          {/* Puntuación mínima */}
          <div className="space-y-3">
            <Label className="text-sm font-medium text-gray-200">
              Puntuación mínima: {filters.minScore}
            </Label>
            <Slider
              disabled={disabled}
              value={[filters.minScore]}
              onValueChange={(value) => updateFilter('minScore', value[0])}
              min={50}
              max={95}
              step={5}
              className="py-3"
            />
            <div className="flex justify-between text-xs text-gray-500">
              <span>50 (Aceptable)</span>
              <span>95 (Excelente)</span>
            </div>
          </div>

          {/* Sector */}
          <div className="space-y-3">
            <Label className="text-sm font-medium text-gray-200">Sector</Label>
            <Select disabled={disabled}
              value={filters.sector}
              onValueChange={(value) => updateFilter('sector', value)}
            >
              <SelectTrigger className="h-11 w-full border-gray-700 bg-gray-900 text-base md:text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sectors.map(sector => (
                  <SelectItem key={sector} value={sector}>
                    {sector === 'all' ? 'Todos los Sectores' : etiquetaSector(sector)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Ordenar por */}
          <div className="space-y-3">
            <Label className="text-sm font-medium text-gray-200">Ordenar por</Label>
            <Select disabled={disabled}
              value={filters.sortBy}
              onValueChange={(value: ProPicksFilters['sortBy']) => updateFilter('sortBy', value)}
            >
              <SelectTrigger className="h-11 w-full border-gray-700 bg-gray-900 text-base md:text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="score">Puntuación general</SelectItem>
                <SelectItem disabled={neutralSorts.includes('momentum')} value="momentum">
                  Momentum{neutralSorts.includes('momentum') ? ' (n/d en estos resultados)' : ''}
                </SelectItem>
                <SelectItem disabled={neutralSorts.includes('value')} value="value">
                  Valor{neutralSorts.includes('value') ? ' (n/d en estos resultados)' : ''}
                </SelectItem>
                <SelectItem value="growth">Crecimiento</SelectItem>
                <SelectItem value="profitability">Rentabilidad</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Botón Aplicar */}
          <Button onClick={onApply} className="h-11 w-full bg-teal-600 hover:bg-teal-700">
            <Filter className="h-4 w-4 mr-2" />
            Aplicar Filtros
          </Button>
        </CardContent>
      </fieldset>
    </Card>
  );
}
