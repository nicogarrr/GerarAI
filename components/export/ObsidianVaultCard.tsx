'use client';

import { useState } from 'react';
import { BookDown } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';

/**
 * Descarga del vault Obsidian del tenant (cartera + watchlist) vía la ruta
 * proxy same-origin /api/obsidian/vault.zip: el navegador nunca ve la firma
 * Research OS. Sin coste: el backend solo empaqueta datos persistidos.
 */
const VAULT_URL = '/api/obsidian/vault.zip';

export default function ObsidianVaultCard() {
    const [confirmOpen, setConfirmOpen] = useState(false);
    return (
        <Card className="rounded-lg border border-gray-700 bg-gray-800/50">
            <CardHeader className="border-b border-gray-700/50 pb-4">
                <div className="flex items-center gap-3">
                    <BookDown className="h-5 w-5 text-teal-400" />
                    <div>
                        <CardTitle className="text-lg font-semibold text-gray-100">Tesis para Obsidian</CardTitle>
                        <CardDescription className="mt-0.5 text-sm text-gray-500">
                            Descarga tus tesis de cartera y watchlist en Markdown enlazado (.zip) para Obsidian.
                        </CardDescription>
                    </div>
                </div>
            </CardHeader>
            <CardContent className="pt-4">
                <button
                    className="mt-6 inline-flex min-h-[44px] items-center gap-2 rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-teal-700 sm:min-h-0"
                    onClick={() => setConfirmOpen(true)}
                    type="button"
                >
                    <BookDown className="h-4 w-4" />
                    Descargar para Obsidian (.zip)
                </button>
                <ConfirmDialog
                    open={confirmOpen}
                    onOpenChange={setConfirmOpen}
                    title="Descargar para Obsidian"
                    description="¿Descargar tus tesis y datos de cartera en un archivo ZIP en este dispositivo?"
                    confirmLabel="Descargar"
                    tone="default"
                    onConfirm={() => { window.location.assign(VAULT_URL); }}
                />
            </CardContent>
        </Card>
    );
}
