'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
    getRadarDcaOpportunities,
    type RadarDcaOpportunity,
    type RadarDcaResult,
} from '@/lib/actions/propicks-radar-dca.actions';

// Misma escala de niveles que la fórmula nico-v1: 4X es la caída más profunda.
const LEVEL_STYLES: Record<number, string> = {
    4: 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300',
    3: 'border-teal-500/40 bg-teal-500/15 text-teal-300',
    2: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
    1: 'border-gray-500/40 bg-gray-600/30 text-gray-300',
    [-1]: 'border-orange-500/40 bg-orange-500/15 text-orange-300',
    [-2]: 'border-red-500/40 bg-red-500/15 text-red-300',
};

function LevelBadge({ item }: { item: RadarDcaOpportunity }) {
    if (item.level == null) return null;
    const style = LEVEL_STYLES[item.level] ?? LEVEL_STYLES[1];
    // Sin línea "Fuente X · barrido · versión" por tarjeta (petición de Nico:
    // la fuente ya se conoce y no aporta en cada fila; los avisos de calidad
    // —precio sin verificación, stale, inválida— se mantienen en StatusLine).
    // Etiqueta única (petición de Nico): para 1-4 el label del motor ya es
    // "N X DCA" — el doble "2X · 2X DCA" repetía el mismo dato. En recortes
    // (-1/-2) el label es "RECORTE LIGERO/FUERTE" y el prefijo "-1X" era un
    // artefacto. Sin label del backend: fallback derivado del nivel.
    const label =
        item.level_label ?? (item.level > 0 ? `${item.level}X DCA` : 'RECORTE');
    return (
        <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${style}`}>
            {label}
        </span>
    );
}

function StatusLine({ item }: { item: RadarDcaOpportunity }) {
    return (
        <div className="flex flex-wrap items-center gap-2 text-xs">
            {item.status === 'forming' && (
                <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-sky-300">En formación</span>
            )}
            {item.status === 'confirmed' && (
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-emerald-300">Confirmado</span>
            )}
            {item.confirmed_level != null && item.confirmed_period && (
                <span className="text-gray-400">
                    Último confirmado: {item.confirmed_level}X · {item.confirmed_period}
                </span>
            )}
            {item.clear_price_signal === true && (
                <span className="rounded-full bg-emerald-500/25 px-2 py-0.5 font-semibold text-emerald-200">
                    4X claro
                </span>
            )}
            {item.price_verified === false && (
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-300">
                    Precio sin verificación independiente
                </span>
            )}
            {item.quality?.passed === true && (
                <span className="rounded-full bg-teal-500/25 px-2 py-0.5 font-semibold text-teal-200">
                    Calidad clara
                </span>
            )}
            {item.change?.status === 'compared' && item.change.changed === true && (
                <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-violet-300">
                    Cambio {item.change.from_level}X → {item.change.to_level}X
                    {item.change.since_price_date ? ` desde ${item.change.since_price_date}` : ''}
                </span>
            )}
        </div>
    );
}

function OpportunityCard({ item }: { item: RadarDcaOpportunity }) {
    return (
        <li>
            <Card className="space-y-2 rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                        <span className="font-semibold text-gray-100">{item.ticker}</span>
                        {item.name && <span className="ml-2 text-sm text-gray-400">{item.name}</span>}
                        {item.sector && <div className="text-xs text-gray-500">{item.sector}</div>}
                    </div>
                    <LevelBadge item={item} />
                </div>
                <StatusLine item={item} />
                <div className="text-sm text-gray-300">
                    {item.close != null && (
                        <span>
                            Cierre {item.close} {item.currency ?? ''}
                            {item.price_date ? ` · ${item.price_date}` : ''}
                        </span>
                    )}
                    {item.signal_date && <span className="text-gray-500"> · señal {item.signal_date}</span>}
                </div>
            </Card>
        </li>
    );
}

export default function RadarDcaView() {
    const [page, setPage] = useState(1);
    const [level, setLevel] = useState<number | null>(null);
    const [sector, setSector] = useState('');
    const [outsideTracked, setOutsideTracked] = useState(false);
    const [qualityClear, setQualityClear] = useState(false);
    const [result, setResult] = useState<RadarDcaResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);
        getRadarDcaOpportunities({ page, level, sector: sector || null, outsideTracked, qualityClear })
            .then((data) => { if (!cancelled) setResult(data); })
            .catch(() => {
                // Sin oportunidades inventadas ni cacheadas: error honesto.
                if (!cancelled) setError('Radar DCA no disponible ahora mismo; no se han generado oportunidades.');
            })
            .finally(() => { if (!cancelled) setLoading(false); });
        return () => { cancelled = true; };
    }, [page, level, sector, outsideTracked, qualityClear]);

    return (
        <section aria-label="Oportunidades DCA" className="space-y-4">
            <p className="text-sm text-gray-400">
                Señales de precio nico-v1 sobre el universo escaneado (hasta 1.000 empresas). Es una
                zona de precio, no un veredicto de calidad de negocio.
            </p>

            <div className="flex flex-wrap items-center gap-2">
                <select
                    aria-label="Nivel"
                    className="min-h-[44px] rounded-md border border-gray-700 bg-gray-800 px-2 text-sm text-gray-200"
                    value={level == null ? '' : String(level)}
                    onChange={(e) => { setPage(1); setLevel(e.target.value === '' ? null : Number(e.target.value)); }}
                >
                    <option value="">Todos los niveles</option>
                    <option value="4">4X</option>
                    <option value="3">3X</option>
                    <option value="2">2X</option>
                    <option value="1">1X</option>
                </select>
                <select
                    aria-label="Sector"
                    className="min-h-[44px] rounded-md border border-gray-700 bg-gray-800 px-2 text-sm text-gray-200"
                    value={sector}
                    onChange={(e) => { setPage(1); setSector(e.target.value); }}
                >
                    <option value="">Todos los sectores</option>
                    {(result?.sectors ?? []).map((s) => (
                        <option key={s} value={s}>{s}</option>
                    ))}
                </select>
                <label className="flex min-h-[44px] items-center gap-2 text-sm text-gray-300">
                    <input
                        type="checkbox"
                        className="h-4 w-4 accent-teal-500"
                        checked={outsideTracked}
                        onChange={(e) => { setPage(1); setOutsideTracked(e.target.checked); }}
                    />
                    Fuera de cartera y watchlist
                </label>
                <label className="flex min-h-[44px] items-center gap-2 text-sm text-gray-300">
                    <input
                        type="checkbox"
                        className="h-4 w-4 accent-teal-500"
                        checked={qualityClear}
                        onChange={(e) => { setPage(1); setQualityClear(e.target.checked); }}
                    />
                    Solo calidad clara
                </label>
            </div>

            {result && (
                <p className="text-xs text-gray-500">
                    Cobertura: {result.coverage.ok} vigentes · {result.coverage.evaluated} evaluadas de{' '}
                    {result.coverage.universe} · {result.coverage.invalid} inválidas ·{' '}
                    {result.coverage.stale} sin corrida reciente
                </p>
            )}

            {loading && (
                <Card aria-busy="true" className="flex items-center justify-center gap-3 rounded-lg border border-gray-700 bg-gray-800/50 p-10 text-gray-400">
                    <Loader2 aria-hidden="true" className="h-5 w-5 animate-spin text-teal-400" />
                    <span>Cargando oportunidades…</span>
                </Card>
            )}

            {!loading && error && (
                <Card className="flex items-center gap-3 rounded-lg border border-amber-700/50 bg-amber-900/20 p-4 text-amber-200">
                    <AlertTriangle aria-hidden="true" className="h-5 w-5 flex-none" />
                    <span className="text-sm">{error}</span>
                </Card>
            )}

            {!loading && !error && result && result.items.length === 0 && (
                <Card className="rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-sm text-gray-400">
                    Sin oportunidades vigentes con estos filtros.
                </Card>
            )}

            {!loading && !error && result && result.items.length > 0 && (
                <ul className="space-y-3">
                    {result.items.map((item) => (
                        <OpportunityCard key={item.ticker} item={item} />
                    ))}
                </ul>
            )}

            {!loading && !error && result && result.total > 0 && (
                <div className="flex items-center justify-between gap-2">
                    <Button
                        className="min-h-[44px]"
                        disabled={page <= 1}
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                        <ChevronLeft aria-hidden="true" className="h-4 w-4" /> Anterior
                    </Button>
                    <span className="text-xs text-gray-500">
                        Página {result.page} · {result.page_size} por página · {result.total} en total
                    </span>
                    <Button
                        className="min-h-[44px]"
                        disabled={!result.has_more}
                        onClick={() => setPage((p) => p + 1)}
                    >
                        Siguiente <ChevronRight aria-hidden="true" className="h-4 w-4" />
                    </Button>
                </div>
            )}
        </section>
    );
}
