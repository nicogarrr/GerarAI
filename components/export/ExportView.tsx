'use client';

import { useState, useSyncExternalStore } from 'react';
import { Download, FileDown, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { exportJournal, type ExportFormat } from '@/lib/actions/export.actions';
import { showErrorToast } from '@/lib/toast';
import { toast } from 'sonner';
import { useT } from '@/lib/i18n/client';

const YEAR_RANGE = 10;

export default function ExportView() {
    const t = useT();
    // El año civil depende del reloj del navegador: leerlo en el render hace
    // que el HTML del servidor y la hidratación difieran en la frontera de
    // año. Se arranca con un estado fijo (0 = todavía sin montar) y se fija
    // el año real tras hidratar (useSyncExternalStore, sin efecto con setState).
    const currentYear = useSyncExternalStore(
        () => () => {},
        () => new Date().getFullYear(),
        () => 0,
    );
    const [year, setYear] = useState(0);
    const [format, setFormat] = useState<ExportFormat>('csv');
    const [loading, setLoading] = useState(false);
    const [preview, setPreview] = useState<string | null>(null);

    const selectedYear = year || currentYear;
    const years = currentYear === 0
        ? []
        : Array.from({ length: YEAR_RANGE + 1 }, (_, index) => currentYear - index);

    const handleExport = async () => {
        setLoading(true);
        setPreview(null);
        try {
            const result = await exportJournal(selectedYear, format);
            const blob = new Blob([result.content], { type: result.contentType });
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = result.filename;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);

            setPreview(result.content.slice(0, 2000));
            toast.success(t('export.journal.success', { filename: result.filename }));
        } catch (error) {
            showErrorToast(error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
            <CardHeader className="border-b border-gray-700/50 pb-4">
                <div className="flex items-center gap-3">
                    <FileDown className="h-5 w-5 text-teal-400" />
                    <div>
                        <CardTitle as="h2" className="text-lg font-semibold text-gray-100">{t('export.journal.title')}</CardTitle>
                        <CardDescription className="mt-0.5 text-sm text-gray-500">
                            {t('export.journal.description')}
                        </CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="pt-4">
                <div className="grid gap-4 sm:grid-cols-2 lg:max-w-2xl">
                    <div className="space-y-2">
                        <Label htmlFor="export-year" className="text-gray-300">{t('export.journal.yearLabel')}</Label>
                        <Select value={String(selectedYear)} onValueChange={(value) => setYear(Number(value))}>
                            <SelectTrigger id="export-year" className="bg-gray-900 border-gray-600 text-gray-100">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent className="bg-gray-900 border-gray-600">
                                {years.map((item) => (
                                    <SelectItem key={item} value={String(item)} className="text-gray-200">
                                        {item}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor="export-format" className="text-gray-300">{t('export.journal.formatLabel')}</Label>
                        <Select value={format} onValueChange={(value) => setFormat(value as ExportFormat)}>
                            <SelectTrigger id="export-format" className="bg-gray-900 border-gray-600 text-gray-100">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent className="bg-gray-900 border-gray-600">
                                <SelectItem value="csv" className="text-gray-200">{t('export.journal.formatCsv')}</SelectItem>
                                <SelectItem value="json" className="text-gray-200">{t('export.journal.formatJson')}</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>

                <Button
                    onClick={handleExport}
                    disabled={loading}
                    className="mt-6 gap-2"
                >
                    {loading ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                        <Download className="h-4 w-4" />
                    )}
                    {loading ? t('export.journal.exporting') : t('export.journal.exportCta')}
                </Button>

                {preview !== null && (
                    <div className="mt-6">
                        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{t('export.journal.preview')}</p>
                        <pre className="max-h-64 overflow-auto rounded-lg border border-gray-700/50 bg-gray-900/50 p-3 text-xs text-gray-400">
                            {preview}
                            {preview.length >= 2000 ? '\n…' : ''}
                        </pre>
                    </div>
                )}
            </CardContent>
        </Card>
    );
}