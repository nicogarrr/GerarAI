'use client';

import { useState } from 'react';
import { AlertTriangle, ExternalLink, Loader2, Radar } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { formatPercent } from '@/lib/format';
import { getRadarCandidates, type RadarCandidate, type RadarResult } from '@/lib/actions/propicks-radar.actions';

const REGION_PRESETS = [
    { id: 'global', label: 'Global', regions: [] },
    { id: 'europa', label: 'Europa', regions: ['es', 'de', 'fr', 'gb', 'it', 'nl', 'se', 'ch'] },
    { id: 'asia', label: 'Asia', regions: ['hk', 'jp'] },
    { id: 'us', label: 'EE. UU.', regions: ['us'] },
];

function YieldValue({ candidate }: { candidate: RadarCandidate }) {
    if (candidate.dividend_yield === null) {
        return <span className="text-sm text-gray-500">N/D</span>;
    }
    return <span className="text-sm text-gray-200">{formatPercent(candidate.dividend_yield)}</span>;
}

export default function RadarGlobalView() {
    const [preset, setPreset] = useState('global');
    const [result, setResult] = useState<RadarResult | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const buscar = async () => {
        setLoading(true);
        setError(null);
        try {
            const active = REGION_PRESETS.find((p) => p.id === preset) ?? REGION_PRESETS[0];
            setResult(await getRadarCandidates(active.regions));
        } catch {
            // Sin candidatos inventados ni cacheados: error honesto.
            setError('Radar de mercado no disponible ahora mismo; no se han generado candidatos.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="space-y-4">
            <p className="text-xs text-gray-500">
                Candidatos sin verificar; conviene cotejo oficial antes de usarlos.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                {REGION_PRESETS.map((p) => (
                    <Button
                        key={p.id}
                        size="sm"
                        variant={preset === p.id ? 'default' : 'outline'}
                        aria-pressed={preset === p.id}
                        onClick={() => setPreset(p.id)}
                        className="min-h-[44px]"
                    >
                        {p.label}
                    </Button>
                ))}
                <Button onClick={buscar} disabled={loading} className="min-h-[44px]">
                    {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Radar className="mr-2 h-4 w-4" />}
                    Buscar candidatos
                </Button>
            </div>
            <p className="text-xs text-gray-500">
                Consulta en vivo al pulsar el botón; puede tardar unos segundos.
            </p>
            {error && (
                <Card className="border-amber-800 bg-amber-950/40 p-4">
                    <p className="text-sm text-amber-200">{error}</p>
                </Card>
            )}
            {result && (
                <>
                    <p className="text-xs text-gray-500">
                        Generado: {new Date(result.generado_en).toLocaleString('es-ES')} · Regiones:{' '}
                        {result.regiones.join(', ') || 'global'}
                    </p>
                    {result.candidatos.length === 0 ? (
                        <p className="text-sm text-gray-400">La consulta no devolvió candidatos con estos filtros.</p>
                    ) : (
                        <div className="grid gap-3 sm:grid-cols-2">
                            {result.candidatos.map((c) => (
                                <Card key={c.symbol} className="border-gray-700 bg-gray-800/60 p-4">
                                    <div className="flex items-start justify-between gap-2">
                                        <div>
                                            <span className="font-semibold text-teal-300">{c.symbol}</span>{' '}
                                            <span className="text-sm text-gray-300">{c.name ?? ''}</span>
                                            <p className="text-xs text-gray-500">
                                                {[c.exchange, c.currency].filter(Boolean).join(' · ')}
                                            </p>
                                        </div>
                                        {c.en_universo_propio && (
                                            <span className="rounded bg-teal-900 px-2 py-0.5 text-xs text-teal-300">
                                                Ya en nuestro universo
                                            </span>
                                        )}
                                    </div>
                                    <div className="mt-3 grid grid-cols-2 gap-2">
                                        <div>
                                            <p className="text-xs text-gray-500">P/B</p>
                                            <p className="text-sm text-gray-200">
                                                {c.price_to_book === null
                                                    ? 'N/D'
                                                    : `${c.price_to_book.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}x`}
                                            </p>
                                        </div>
                                        <div>
                                            <p className="text-xs text-gray-500">Dividendo</p>
                                            <YieldValue candidate={c} />
                                        </div>
                                    </div>
                                    {c.yield_extremo_revisar && (
                                        <p className="mt-2 flex items-center gap-1 text-xs text-amber-400">
                                            <AlertTriangle className="h-3 w-3" /> Yield muy alto: revisar si es un dividendo especial
                                        </p>
                                    )}
                                    {c.via_cotejo && (
                                        <a
                                            href={c.via_cotejo}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="mt-2 inline-flex min-h-[44px] items-center gap-1 text-xs text-teal-400 underline"
                                        >
                                            Cotejar en HKEXnews (fuente oficial) <ExternalLink className="h-3 w-3" />
                                        </a>
                                    )}
                                </Card>
                            ))}
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
