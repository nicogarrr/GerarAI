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
import { useT } from '@/lib/i18n/client';
import type { TranslationKey } from '@/lib/i18n/t';
import dynamic from 'next/dynamic';

// El visor markdown (~47 KB gzip) solo hace falta con un documento ya
// generado en pantalla: no viaja ni siquiera en el chunk del diálogo.
function ViewerLoading() {
    const t = useT();
    return <p className="text-sm text-gray-500">{t('workProducts.loadingViewer')}</p>;
}
const ThesisMarkdown = dynamic(() => import('@/components/research/ThesisMarkdown'), {
    loading: ViewerLoading,
});
import { toast } from 'sonner';

const PRODUCT_TYPES: Array<{ value: WorkProductType; labelKey: TranslationKey }> = [
    { value: 'one_page_memo', labelKey: 'workProducts.types.onePageMemo' },
    { value: 'full_thesis', labelKey: 'workProducts.types.fullThesis' },
    { value: 'earnings_review', labelKey: 'workProducts.types.earningsReview' },
    { value: 'valuation_memo', labelKey: 'workProducts.types.valuationMemo' },
    { value: 'capital_allocation_analysis', labelKey: 'workProducts.types.capitalAllocation' },
    { value: 'comparables', labelKey: 'workProducts.types.comparables' },
    { value: 'portfolio_review', labelKey: 'workProducts.types.portfolioReview' },
    { value: 'risk_report', labelKey: 'workProducts.types.riskReport' },
];

/**
 * Contenido del diálogo «Generar entregable»: tipo de documento, ticker
 * opcional, años y el resultado en markdown. Carga diferido al abrir el
 * diálogo (ver WorkProductButton).
 */
export default function WorkProductDialog() {
    const t = useT();
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
            toast.success(t('workProducts.generated'));
        } catch (error) {
            showErrorToast(error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <DialogContent className="border-gray-700 bg-gray-800 max-h-[90dvh] overflow-y-auto">
            <DialogHeader>
                <DialogTitle className="text-gray-100">{t('workProducts.title')}</DialogTitle>
                <DialogDescription className="text-gray-400">
                    {t('workProducts.description')}
                </DialogDescription>
            </DialogHeader>

            <div className="mt-4 space-y-4">
                <div className="space-y-2">
                    <Label htmlFor="wp-type" className="text-gray-300">{t('workProducts.typeLabel')}</Label>
                    <Select value={productType} onValueChange={(value) => setProductType(value as WorkProductType)}>
                        <SelectTrigger id="wp-type" className="bg-gray-900 border-gray-600 text-gray-100">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent className="bg-gray-900 border-gray-600">
                            {PRODUCT_TYPES.map((type) => (
                                <SelectItem key={type.value} value={type.value} className="text-gray-200">
                                    {t(type.labelKey)}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                <div className="space-y-2">
                    <Label htmlFor="wp-ticker" className="text-gray-300">
                        Ticker <span className="text-gray-500">{t('workProducts.optional')}</span>
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
                    <Label htmlFor="wp-years" className="text-gray-300">{t('workProducts.yearsLabel')}</Label>
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
                    <span>{loading ? t('workProducts.generating') : t('workProducts.generate')}</span>
                </Button>

                {result && (
                    <div>
                        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{t('workProducts.result')}</p>
                        <div className="max-h-96 overflow-auto rounded-lg border border-gray-700/50 bg-gray-900/50 p-4 text-sm text-gray-300">
                            {typeof result.markdown === 'string' && result.markdown.trim() ? (
                                <ThesisMarkdown content={result.markdown} />
                            ) : (
                                <p className="text-gray-500">{t('workProducts.emptyContent')}</p>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </DialogContent>
    );
}
