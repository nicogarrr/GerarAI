'use client';

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ShareCapital } from '@/lib/actions/share-capital.actions';
import { formatCompact, formatMarketDate } from '@/lib/format';

const compact = (value: number) => formatCompact(value);

/**
 * Gráfica de evolución de acciones (recharts, ~120 KB gzip con sus d3).
 * Vive en su propio chunk y se carga diferida desde ShareCapitalPanel:
 * la tabla de saldos -el dato- pinta al instante y la librería de gráficas
 * no viaja en el bundle inicial de /research/[ticker]/share-capital.
 */
export default function ShareCapitalChart({ series }: { series: ShareCapital['series'] }) {
  return (
    <ResponsiveContainer width="100%" height="100%"><LineChart data={series} margin={{ left: 8, right: 16, top: 10, bottom: 10 }}>
      <CartesianGrid stroke="#374151" strokeDasharray="3 3" /><XAxis dataKey="date" tickFormatter={(value) => formatMarketDate(String(value), { month: 'short', year: '2-digit' })} tick={{ fontSize: 10, fill: '#9ca3af' }} minTickGap={32} />
      <YAxis tickFormatter={compact} tick={{ fontSize: 10, fill: '#9ca3af' }} width={65} domain={['auto', 'auto']} />
      <Tooltip formatter={(value) => [compact(Number(value)), 'Acciones']} labelFormatter={(value) => formatMarketDate(String(value))} contentStyle={{ background: '#111827', border: '1px solid #374151', color: '#f3f4f6' }} />
      <Line type="linear" dataKey="value" stroke="#2dd4bf" dot={false} strokeWidth={2} isAnimationActive={false} />
    </LineChart></ResponsiveContainer>
  );
}
