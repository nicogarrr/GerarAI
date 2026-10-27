'use client';

import { useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ImagePlus, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { confirmPortfolioImage, previewPortfolioImage, reviewPortfolioImage, searchImageInstrument } from '@/lib/actions/portfolio-image.actions';
import { imageFileError, type ImageInstrument, type ImagePreview, type ImageReview } from '@/lib/portfolio/image-import';
import { formatMoney, formatNumber, formatPercent } from '@/lib/format';
import { toast } from 'sonner';

type Draft = { query: string; instrument: ImageInstrument | null; quantity: string; checked: boolean };

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
        <DialogContent className="max-h-[85dvh] overflow-y-auto text-gray-100 [&>button]:z-20 sm:max-w-xl" showCloseButton={!busy}>
            <DialogHeader className="sticky -top-6 z-10 -mx-6 -mt-6 bg-gray-800 px-6 pb-3 pt-6"><DialogTitle>Importar cartera desde una captura</DialogTitle><DialogDescription>Lectura local, sin enviar la imagen a una IA externa. Revisa antes de guardar. La imagen no se conserva.</DialogDescription></DialogHeader>
            <p className="text-sm text-gray-300">Incluye la cabecera de cantidad y las posiciones. PNG, JPEG o WebP, máximo 2 MB. No se importan los precios de la imagen.</p>
            <label className="grid min-h-11 cursor-pointer gap-2 rounded border border-gray-600 p-3 text-center text-sm">Elegir captura<Input aria-label="Elegir captura" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} className="sr-only" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void selectFile(file); }} /></label>
            {busy && <p role="status" className="flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Leyendo o revisando. Puede tardar unos segundos...</p>}
            {error && <p role="alert" className="rounded border border-red-700 p-3 text-sm text-red-200">{error}</p>}
            {preview && <p className="text-sm text-gray-300">{preview.message}</p>}
            {!review && drafts.map((row, index) => <section key={index} className="grid gap-3 rounded-lg border border-gray-600 p-3" aria-label={`Fila ${index + 1}`}>
                <p className="break-words text-xs text-gray-400">Leído: {preview?.rows[index]?.raw ?? 'Fila manual'}</p>
                <p className="text-xs text-amber-200">{preview?.rows[index]?.warning ?? 'Revisa esta fila'}</p>
                <label className="grid gap-1 text-sm">Instrumento<Input value={row.query} disabled={busy} onChange={e => change(index, { query: e.target.value, instrument: null })} /></label>
                <Button variant="outline" disabled={busy || !row.query.trim()} onClick={() => void run(async () => { const version = generation.current; const items = await searchImageInstrument(row.query); if (generation.current === version) setMatches({ index, items }); })}>Buscar instrumento</Button>
                {matches?.index === index && <div className="grid gap-2">{matches.items.length === 0 && <p className="text-sm">Sin coincidencias. Busca por ticker o nombre.</p>}{matches.items.map(item => <Button key={item.ticker} variant="outline" className="h-auto min-h-11 justify-start whitespace-normal text-left" disabled={busy} onClick={() => change(index, { instrument: item, query: item.ticker })}>{item.ticker} · {item.name} · {item.exchange} · {item.currency}</Button>)}</div>}
                {row.instrument && <p className="text-sm text-green-200">{row.instrument.name} · {row.instrument.exchange} · {row.instrument.currency}</p>}
                <label className="grid gap-1 text-sm">Cantidad (decimal con punto, sin separador de miles)<Input inputMode="decimal" value={row.quantity} disabled={busy} onChange={e => change(index, { quantity: e.target.value })} /></label>
                <label className="flex min-h-11 items-center gap-3 text-sm"><input type="checkbox" checked={row.checked} disabled={busy || !row.instrument} onChange={e => { setReview(null); setDrafts(old => old.map((d, i) => i === index ? { ...d, checked: e.target.checked } : d)); }} />He revisado instrumento, cantidad y divisa</label>
                <Button variant="ghost" disabled={busy} onClick={() => { generation.current++; setMatches(null); setDrafts(old => old.filter((_, i) => i !== index)); setPreview(old => old ? { ...old, rows: old.rows.filter((_, i) => i !== index) } : old); }}>Omitir fila</Button>
            </section>)}
            {preview && !review && <>
                <Button variant="outline" disabled={busy || drafts.length >= 60} onClick={() => { setDrafts(old => [...old, { query: '', instrument: null, quantity: '', checked: false }]); setPreview(old => old ? { ...old, rows: [...old.rows, { raw: 'Fila manual', identity: '', quantity: null, currency: null, warning: 'Completa los datos ilegibles' }] } : old); }}>Añadir fila ilegible manualmente</Button>
                <Button disabled={busy || !ready} onClick={() => void run(async () => { const rows = drafts.map(r => ({ ticker: r.instrument!.ticker, quantity: r.quantity, currency: r.instrument!.currency, confirmed: r.checked })); setReview(await reviewPortfolioImage(preview.image_hash, rows)); })}>Consultar precios y revisar</Button>
            </>}
            {review && <>
                <h3 className="font-semibold">Revisión final</h3>
                {review.rows.map(row => <div key={row.ticker} className="grid gap-1 rounded border border-gray-600 p-3 text-sm">
                    <p>{row.ticker} · {row.name} · {formatNumber(Number(row.quantity), { maximumFractionDigits: 6 })} acciones</p>
                    <p>Precio: {row.price ? formatMoney(Number(row.price), row.currency) : 'No disponible'}</p>
                    <p>Valor: {row.value_base ? formatMoney(Number(row.value_base), review.base_currency) : 'No disponible'} · Peso entre estas filas: {row.weight_percent ? formatPercent(Number(row.weight_percent), { fromRatio: false, digits: 1 }) : 'N/D'}</p>
                    <p className="text-xs text-gray-400">{row.source}{row.timestamp ? ` · ${new Date(row.timestamp * 1000).toLocaleString('es-ES')}` : ''}</p>
                </div>)}
                {!review.can_confirm && <p role="alert" className="text-sm text-amber-200">Faltan cotizaciones actuales. No se guardará nada; vuelve a consultar más tarde.</p>}
                <Button variant="outline" disabled={busy} onClick={() => setReview(null)}>Corregir filas</Button>
                <Button disabled={busy || !review.can_confirm || review.already_imported} onClick={() => void run(async () => { const result = await confirmPortfolioImage(review.review_id); toast.success(result.status === 'already_imported' ? 'Esta importación ya estaba guardada' : `${result.positions_imported} posiciones importadas`); setOpen(false); setPreview(null); setDrafts([]); setReview(null); router.refresh(); })}>Confirmar y guardar posiciones</Button>
            </>}
            <p className="text-xs text-gray-400">Solo posiciones nuevas. No sustituye posiciones existentes ni reconstruye operaciones, coste de compra o rentabilidad histórica. Caja y margen siguen sin determinar; los pesos de revisión solo incluyen estas filas. Para conciliar una cartera existente, usa el fichero del bróker.</p>
        </DialogContent>
    </Dialog>;
}
