'use client';

import { useState } from 'react';
import { BookDown } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { useT } from '@/lib/i18n/client';

/**
 * Descarga del vault Obsidian del tenant (cartera + watchlist) vía la ruta
 * proxy same-origin /api/obsidian/vault.zip: el navegador nunca ve la firma
 * Research OS. Sin coste: el backend solo empaqueta datos persistidos.
 */
const VAULT_URL = '/api/obsidian/vault.zip';

export default function ObsidianVaultCard() {
    const t = useT();
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [downloading, setDownloading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Descarga por fetch + blob: un 502 del proxy NO saca al usuario a un JSON de error
    // fuera de la app (una navegación directa al proxy sí lo haría); el fallo queda inline en
    // la tarjeta. Sin JS el enlace descarga directo (mejora progresiva).
    const handleDownload = async () => {
        setDownloading(true);
        setError(null);
        try {
            const response = await fetch(VAULT_URL);
            if (!response.ok) throw new Error(`vault HTTP ${response.status}`);
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'gerarai-obsidian-vault.zip';
            link.click();
            // Revocación diferida: revocar en el mismo tick puede cortar la
            // descarga en Safari/iOS antes de que empiece.
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch {
            setError(t('export.obsidian.error'));
        } finally {
            setDownloading(false);
        }
    };

    return (
        <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
            <CardHeader className="border-b border-gray-700/50 pb-4">
                <div className="flex items-center gap-3">
                    <BookDown className="h-5 w-5 text-teal-400" />
                    <div>
                        <CardTitle className="text-lg font-semibold text-gray-100">{t('export.obsidian.title')}</CardTitle>
                        <CardDescription className="mt-0.5 text-sm text-gray-500">
                            {t('export.obsidian.description')}
                        </CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="pt-4">
                <a
                    aria-busy={downloading}
                    className="mt-6 inline-flex min-h-[44px] items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:bg-primary/90 sm:min-h-0"
                    href="/api/obsidian/vault.zip"
                    onClick={(event) => {
                        event.preventDefault();
                        if (!downloading) setConfirmOpen(true);
                    }}
                    download
                >
                    <BookDown className="h-4 w-4" />
                    {downloading ? t('export.obsidian.downloading') : t('export.obsidian.cta')}
                </a>
                {error ? (
                    <p className="mt-2 text-sm text-red-400" role="alert">{error}</p>
                ) : null}
                <ConfirmDialog
                    open={confirmOpen}
                    onOpenChange={setConfirmOpen}
                    title={t('export.obsidian.confirmTitle')}
                    description={t('export.obsidian.confirmDescription')}
                    confirmLabel={t('export.obsidian.confirmLabel')}
                    tone="default"
                    onConfirm={handleDownload}
                />
            </CardContent>
        </Card>
    );
}
