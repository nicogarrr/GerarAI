'use client';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    generateWorkProduct,
    type WorkProductRecord,
    type WorkProductType,
} from '@/lib/actions/work-products.actions';
import { showErrorToast } from '@/lib/toast';
import dynamic from 'next/dynamic';

// El visor markdown (~47 KB gzip) solo hace falta con un documento ya
// generado en pantalla: no viaja ni siquiera en el chunk del diálogo.
const ThesisMarkdown = dynamic(() => import('@/components/research/ThesisMarkdown'), {
    loading: () => <p className="text-sm text-gray-500">Cargando visor...</p>,
});
import { toast } from 'sonner';

const PRODUCT_TYPES: Array<{ value: WorkProductType; label: string }> = [
    { value: 'one_page_memo', label: 'Memo de una página' },
    { value: 'full_thesis', label: 'Tesis completa' },
    { value: 'earnings_review', label: 'Revisión de earnings' },
    { value: 'valuation_memo', label: 'Memo de valoración' },
    { value: 'capital_allocation_analysis', label: 'Análisis de asignación de capital' },
    { value: 'comparables', label: 'Comparables' },
    { value: 'portfolio_review', label: 'Revisión de cartera' },
    { value: 'risk_report', label: 'Informe de riesgo' },
];

/**
 * Contenido del diálogo «Generar entregable»: tipo de documento, ticker
 * opcional, años y el resultado en markdown. Carga diferido al abrir el
 * diálogo (ver WorkProductButton).
 */
export default function WorkProductDialog() {
    const [productType, setProductType] = useState<WorkProductType>('one_page_memo');
    const [ticker, setTicker] = useState('');
    const [years, setYears] = useState('10');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<WorkProductRecord | null>(null);

    const handleGenerate = async () => {
        setLoading(true);
        setResult(null);
        try {
            const generated = await generateWorkProduct({
                product_type: productType,
                ticker: ticker.trim() || null,
                years: Math.min(20, Math.max(1, Number(years) || 10)),
            });
            setResult(generated);
            toast.success('Entregable generado');
        } catch (error) {
            showErrorToast(error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <DialogContent className="border-gray-700 bg-gray-800">
            <DialogHeader>
                <DialogTitle className="text-gray-100">Generar entregable</DialogTitle>
                <DialogDescription className="text-gray-400">
                    Produce un documento de análisis (memo, tesis, revisión...) a partir del motor de research.
                </DialogDescription>
            </DialogHeader>

            <div className="mt-4 space-y-4">
                <div className="space-y-2">
                    <Label htmlFor="wp-type" className="text-gray-300">Tipo de documento</Label>
                    <Select value={productType} onValueChange={(value) => setProductType(value as WorkProductType)}>
                        <SelectTrigger id="wp-type" className="bg-gray-900 border-gray-600 text-gray-100">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-gray-900 border-gray-600">
                            {PRODUCT_TYPES.map((type) => (
                                <SelectItem key={type.value} value={type.value} className="text-gray-200">
                                    {type.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                <div className="space-y-2">
                    <Label htmlFor="wp-ticker" className="text-gray-300">
                        Ticker <span className="text-gray-500">(opcional)</span>
                    </Label>
                    <TickerSearchInput
                        id="wp-ticker"
                        value={ticker}
                        onValueChange={setTicker}
                        onSelect={(stock) => setTicker(stock.symbol)}
                        placeholder="AAPL"
                        className="bg-gray-900 border-gray-600 text-gray-100"
                    />
                </div>

                <div className="space-y-2">
                    <Label htmlFor="wp-years" className="text-gray-300">Años de histórico</Label>
                    <Input
                        id="wp-years"
                        type="number"
                        min={1}
                        max={20}
                        value={years}
                        onChange={(event) => setYears(event.target.value)}
                        className="bg-gray-900 border-gray-600 text-gray-100"
                    />
                </div>

                {/* QA /research: el texto no puede desaparecer mientras
                    genera (quedaba una barra teal vacía): el primario y la
                    etiqueta siempre presentes junto al spinner. */}
                <Button onClick={handleGenerate} disabled={loading} aria-busy={loading} className="w-full gap-2">
                    {loading && <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin" />}
                    <span>{loading ? 'Generando...' : 'Generar documento'}</span>
                </Button>

                {result && (
                    <div>
                        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">Resultado</p>
                        <div className="max-h-96 overflow-auto rounded-lg border border-gray-700/50 bg-gray-900/50 p-4 text-sm text-gray-300">
                            {typeof result.markdown === 'string' && result.markdown.trim() ? (
                                <ThesisMarkdown content={result.markdown} />
                            ) : (
                                <p className="text-gray-500">El entregable no trajo contenido.</p>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </DialogContent>
    );
}
