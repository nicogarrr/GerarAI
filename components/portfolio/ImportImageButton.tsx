'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Check, ChevronRight, ImagePlus, Loader2, Search, ShieldCheck, Upload, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { confirmPortfolioImage, previewPortfolioImage, reviewPortfolioImage, searchImageInstrument } from '@/lib/actions/portfolio-image.actions';
import { imageFileError, type ImageInstrument, type ImagePreview, type ImageReview } from '@/lib/portfolio/image-import';
import { formatMoney, formatNumber, formatPercent } from '@/lib/format';
import { toast } from 'sonner';

type Draft = { query: string; instrument: ImageInstrument | null; quantity: string; checked: boolean };

/** Toast de confirmación: concordancia es-ES («1 posición importada»). */
export function importedPositionsMessage(imported: number): string {
    return `${formatNumber(imported, { maximumFractionDigits: 0 })} ${imported === 1 ? 'posición importada' : 'posiciones importadas'}`;
}

export default function ImportImageButton() {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [preview, setPreview] = useState<ImagePreview | null>(null);
    const [drafts, setDrafts] = useState<Draft[]>([]);
    const [review, setReview] = useState<ImageReview | null>(null);
    const [matches, setMatches] = useState<{ index: number; items: ImageInstrument[] } | null>(null);
    const generation = useRef(0);
    const lock = useRef(false);
    const router = useRouter();
    const fileInput = useRef<HTMLInputElement>(null);

    async function run(action: () => Promise<void>) {
        if (lock.current) return;
        lock.current = true; setBusy(true); setError(null);
        try { await action(); } catch (e) { setError(e instanceof Error ? e.message : 'No se pudo completar la importación'); }
        finally { lock.current = false; setBusy(false); }
    }

    function change(index: number, fields: Partial<Draft>) {
        generation.current++; setMatches(null); setReview(null);
        setDrafts(old => old.map((row, i) => i === index ? { ...row, ...fields, checked: false } : row));
    }

    async function selectFile(file: File) {
        setPreview(null); setReview(null); setDrafts([]); setMatches(null); generation.current++;
        const invalid = imageFileError(file);
        if (invalid) { setError(invalid); return; }
        await run(async () => {
            const encoded = await new Promise<string>((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result).split(',')[1]);
                reader.onerror = () => reject(new Error('No se pudo abrir la imagen'));
                reader.readAsDataURL(file);
            });
            const result = await previewPortfolioImage(encoded);
            setPreview(result);
            setDrafts(result.rows.map(row => ({ query: row.identity, instrument: null, quantity: row.quantity ?? '', checked: false })));
        });
    }

    const ready = drafts.length > 0 && drafts.every(row => row.instrument && row.checked && /^\d+(?:\.\d{1,6})?$/.test(row.quantity) && Number(row.quantity) > 0);
    return <Dialog open={open} onOpenChange={next => { if (!busy) { setOpen(next); generation.current++; if (!next) { setPreview(null); setDrafts([]); setReview(null); setMatches(null); setError(null); } } }}>
        <DialogTrigger asChild><Button variant="outline" size="sm" className="min-h-11 border-gray-600 text-gray-200 sm:min-h-8"><ImagePlus className="mr-2 h-4 w-4" aria-hidden="true" />Importar captura</Button></DialogTrigger>
        <DialogContent className="flex max-h-[90dvh] flex-col gap-0 overflow-hidden border-gray-700 bg-gray-900 p-0 text-gray-100 [&>button]:z-20 sm:max-w-xl" showCloseButton={!busy}>
            <DialogHeader className="border-b shrink-0 border-gray-800 px-5 pb-4 pt-5 text-left sm:px-6">
                <div className="mb-1 flex items-center gap-2 text-xs font-medium text-emerald-300"><ShieldCheck className="h-4 w-4" aria-hidden="true" />Lectura local · sin guardar la imagen</div>
                <DialogTitle className="pr-6 text-xl leading-tight">Importar captura</DialogTitle>
                <DialogDescription className="text-gray-400">Tu cartera, con precios de mercado. Tú revisas antes de guardar.</DialogDescription>
                <ol aria-label="Pasos de importación" className="mt-3 flex items-center gap-2 text-xs text-gray-500">
                    {['Captura', 'Posiciones', 'Confirmar'].map((label, index) => {
                        const step = review ? 2 : preview ? 1 : 0;
                        return <li key={label} className={`flex items-center gap-2 ${index === step ? 'font-semibold text-gray-100' : index < step ? 'text-emerald-300' : ''}`}>
                            {index > 0 && <ChevronRight className="h-3 w-3 text-gray-600" aria-hidden="true" />}
                            <span className={`flex h-5 w-5 items-center justify-center rounded-full ${index <= step ? 'bg-emerald-400/15 text-emerald-300' : 'bg-gray-800'}`}>{index < step ? <Check className="h-3 w-3" aria-hidden="true" /> : index + 1}</span>{label}
                        </li>;
                    })}
                </ol>
            </DialogHeader>
            <div className="min-h-0 min-w-0 overflow-x-hidden overflow-y-auto px-5 py-5 sm:px-6">
            <input ref={fileInput} aria-label="Elegir captura" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} className="sr-only" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void selectFile(file); }} />
            {!preview ? <button type="button" disabled={busy} onClick={() => fileInput.current?.click()} className="group flex min-h-48 w-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-gray-600 bg-gray-800/40 px-5 py-6 text-center transition-colors hover:border-emerald-400/60 hover:bg-gray-800 focus-visible:outline-2 focus-visible:outline-emerald-400 disabled:opacity-50">
                <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-400/10 text-emerald-300"><Upload className="h-6 w-6" aria-hidden="true" /></span>
                <span className="font-semibold">Elegir captura</span><span className="max-w-64 text-sm text-gray-400">Incluye las posiciones y la cabecera de cantidad.</span><span className="text-xs text-gray-500">PNG, JPEG o WebP · hasta 2 MB</span>
            </button> : !review && <div className="mb-4 flex items-center justify-between gap-3"><p className="text-sm text-gray-400">{drafts.length} {drafts.length === 1 ? 'fila para revisar' : 'filas para revisar'}</p><Button variant="ghost" size="sm" disabled={busy} onClick={() => fileInput.current?.click()}>Cambiar captura</Button></div>}
            {busy && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Leyendo o revisando. Puede tardar unos segundos...</p>}
            {error && <p role="alert" className="rounded border border-red-700 p-3 text-sm text-red-200">{error}</p>}
            {preview && drafts.length === 0 && !review && <p className="my-3 text-sm text-amber-200">{preview.message}</p>}
            {!review && drafts.map((row, index) => <section key={index} className="mb-3 grid gap-3 rounded-xl border border-gray-700 bg-gray-800/30 p-4" aria-label={`Fila ${index + 1}`}>
                <div className="flex items-center justify-between gap-2"><span className="text-xs font-medium uppercase tracking-wide text-gray-400">Posición {index + 1}</span><span className={`text-xs ${row.checked ? 'text-emerald-300' : 'text-amber-200'}`}>{row.checked ? 'Revisada' : 'Por revisar'}</span></div>
                <details className="text-xs text-gray-500"><summary className="cursor-pointer">Texto leído en la captura</summary><p className="mt-2 break-words text-gray-400">Leído: {preview?.rows[index]?.raw ?? 'Fila manual'}</p></details>
                <label className="grid gap-1 text-sm">Instrumento<Input value={row.query} disabled={busy} onChange={e => change(index, { query: e.target.value, instrument: null })} /></label>
                <Button variant="outline" className="min-h-11" disabled={busy || !row.query.trim()} onClick={() => void run(async () => { const version = generation.current; const items = await searchImageInstrument(row.query); if (generation.current === version) setMatches({ index, items }); })}><Search className="h-4 w-4" aria-hidden="true" />Buscar instrumento</Button>
                {matches?.index === index && <div className="grid gap-2">{matches.items.length === 0 && <p className="text-sm">Sin coincidencias. Busca por ticker o nombre.</p>}{matches.items.map(item => <Button key={item.ticker} variant="outline" className="h-auto min-h-11 justify-start whitespace-normal text-left" disabled={busy} onClick={() => change(index, { instrument: item, query: item.ticker })}>{item.ticker} · {item.name} · {item.exchange} · {item.currency}</Button>)}</div>}
                {row.instrument && <p className="text-sm text-green-200">{row.instrument.name} · {row.instrument.exchange} · {row.instrument.currency}</p>}
                <label className="grid gap-1 text-sm">Cantidad<Input inputMode="decimal" placeholder="Ej. 125.5 (sin miles)" className="h-11 text-base" value={row.quantity} disabled={busy} onChange={e => change(index, { quantity: e.target.value })} /></label>
                <label className="flex min-h-11 items-center gap-3 text-sm"><input className="h-5 w-5 accent-emerald-400" type="checkbox" checked={row.checked} disabled={busy || !row.instrument} onChange={e => { setReview(null); setDrafts(old => old.map((d, i) => i === index ? { ...d, checked: e.target.checked } : d)); }} />He revisado instrumento, cantidad y divisa</label>
                <Button variant="ghost" disabled={busy} onClick={() => { generation.current++; setMatches(null); setDrafts(old => old.filter((_, i) => i !== index)); setPreview(old => old ? { ...old, rows: old.rows.filter((_, i) => i !== index) } : old); }}><X className="h-4 w-4" aria-hidden="true" />Omitir fila</Button>
            </section>)}
            {preview && !review && <>
                <Button className="mb-3 min-h-11 w-full whitespace-normal" variant="outline" disabled={busy || drafts.length >= 60} onClick={() => { setDrafts(old => [...old, { query: '', instrument: null, quantity: '', checked: false }]); setPreview(old => old ? { ...old, rows: [...old.rows, { raw: 'Fila manual', identity: '', quantity: null, currency: null, warning: 'Completa los datos ilegibles' }] } : old); }}>Añadir fila ilegible manualmente</Button>
                <Button className="mb-3 min-h-11 w-full bg-emerald-400 text-gray-950 hover:bg-emerald-300" disabled={busy || !ready} onClick={() => void run(async () => { const rows = drafts.map(r => ({ ticker: r.instrument!.ticker, quantity: r.quantity, currency: r.instrument!.currency, confirmed: r.checked })); setReview(await reviewPortfolioImage(preview.image_hash, rows)); })}>Consultar precios y revisar</Button>
            </>}
            {review && <>
                <div className="mb-4"><h3 className="font-semibold">Revisión final</h3><p className="mt-1 text-sm text-gray-400">Precios consultados en mercado, no extraídos de la imagen.</p></div>
                {review.rows.map(row => <div key={row.ticker} className="mb-3 overflow-hidden rounded-xl border border-gray-700 bg-gray-800/40 text-sm">
                    <div className="flex items-start justify-between gap-3 border-b border-gray-700/60 p-4"><div className="min-w-0"><p className="text-base font-semibold">{row.ticker}</p><p className="mt-1 truncate text-xs text-gray-400">{row.name}</p></div><span className="shrink-0 rounded bg-gray-700/50 px-2 py-1 text-xs">{formatNumber(Number(row.quantity), { maximumFractionDigits: 6 })} acciones</span></div>
                    <dl className="grid grid-cols-2 gap-4 p-4"><div><dt className="text-xs text-gray-400">Precio · {row.currency}</dt><dd className="mt-1 text-base font-medium tabular-nums">{row.price ? formatMoney(Number(row.price), row.currency) : 'No disponible'}</dd></div><div><dt className="text-xs text-gray-400">Valor · {review.base_currency}</dt><dd className="mt-1 text-base font-medium tabular-nums">{row.value_base ? formatMoney(Number(row.value_base), review.base_currency) : 'No disponible'}</dd></div></dl>
                    <div className="flex justify-between gap-3 px-4 pb-4 text-xs text-gray-400"><span>Peso entre estas filas</span><span className="tabular-nums text-gray-200">{row.weight_percent ? formatPercent(Number(row.weight_percent), { fromRatio: false, digits: 1 }) : 'N/D'}</span></div>
                    <p className="border-t border-gray-700/60 px-4 py-3 text-xs leading-relaxed text-gray-500">{row.source}{row.timestamp ? ` · ${new Date(row.timestamp * 1000).toLocaleString('es-ES')}` : ''}</p>
                </div>)}
                {!review.can_confirm && <p role="alert" className="text-sm text-amber-200">Faltan cotizaciones actuales. No se guardará nada; vuelve a consultar más tarde.</p>}
                </>}
            <details className="mt-4 text-xs leading-relaxed text-gray-500"><summary className="cursor-pointer text-gray-400">Qué se importa y qué no</summary><p className="mt-2">Solo posiciones nuevas. No sustituye las existentes ni reconstruye compras, coste o rentabilidad histórica. Caja y margen no se determinan. Para conciliar una cartera existente, usa el fichero del bróker.</p></details>
            </div>
            {review && <div className="grid shrink-0 gap-2 border-t border-gray-800 bg-gray-900 px-5 py-4 sm:px-6"><p className="mb-1 text-xs text-gray-400">Solo posiciones nuevas. Coste, caja y margen no determinados.</p><Button className="min-h-11 w-full bg-emerald-400 text-gray-950 hover:bg-emerald-300" disabled={busy || !review.can_confirm || review.already_imported} onClick={() => void run(async () => { const result = await confirmPortfolioImage(review.review_id); toast.success(result.status === 'already_imported' ? 'Esta importación ya estaba guardada' : importedPositionsMessage(result.positions_imported)); setOpen(false); setPreview(null); setDrafts([]); setReview(null); router.refresh(); })}>Confirmar y guardar posiciones</Button><Button className="min-h-11" variant="ghost" disabled={busy} onClick={() => setReview(null)}>Corregir filas</Button></div>}
        </DialogContent>
    </Dialog>;
}
