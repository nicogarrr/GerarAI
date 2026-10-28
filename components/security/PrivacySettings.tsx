'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Download, ShieldAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { deleteAccount, exportAccountData } from '@/lib/actions/privacy.actions';

export default function PrivacySettings({ email }: { email: string }) {
    const router = useRouter();
    const [exporting, setExporting] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [confirmation, setConfirmation] = useState('');
    const [password, setPassword] = useState('');
    const [understood, setUnderstood] = useState(false);

    const handleExport = async () => {
        setExporting(true);
        try {
            const result = await exportAccountData();
            const blob = new Blob([result.content], { type: result.contentType });
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = result.filename;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            URL.revokeObjectURL(url);
            toast.success('Exportación descargada');
        } catch (error) {
            toast.error('No se pudo exportar', {
                description: error instanceof Error ? error.message : 'Inténtalo de nuevo.',
            });
        } finally {
            setExporting(false);
        }
    };

    const handleDelete = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (!understood) {
            toast.error('Confirma que has leído la advertencia');
            return;
        }
        setDeleting(true);
        try {
            const result = await deleteAccount({ confirmation, password });
            if (!result.success) {
                toast.error('No se borró la cuenta', { description: result.message });
                return;
            }
            toast.success('Cuenta eliminada', { description: result.message });
            router.push('/sign-in');
            router.refresh();
        } catch {
            toast.error('No se borró la cuenta', {
                description: 'La sesión no está disponible. Vuelve a iniciar sesión.',
            });
        } finally {
            setDeleting(false);
        }
    };

    return (
        <div className="min-w-0 space-y-8">
            <section className="min-w-0 rounded-lg border border-gray-800 p-5">
                <h2 className="break-words text-xl font-semibold text-white">Exportar mis datos</h2>
                <p className="mt-1 text-sm text-gray-400">
                    Descarga un JSON con tus datos estructurados y metadatos: perfil,
                    cartera, tesis, claims y evidencia, watchlist, alertas, conocimiento,
                    planes y ajustes. Los archivos originales de los documentos no se
                    incluyen; de cada documento solo viajan sus metadatos y el recuento
                    de fragmentos.
                </p>
                <Button
                    className="mt-4 w-full min-w-0 whitespace-normal text-left sm:w-auto"
                    disabled={exporting}
                    onClick={handleExport}
                    type="button"
                    variant="outline"
                >
                    <Download aria-hidden="true" />
                    {exporting ? 'Preparando exportación…' : 'Exportar todos mis datos'}
                </Button>
            </section>

            <section className="min-w-0 rounded-lg border border-red-900/60 bg-red-950/10 p-5">
                <div className="flex min-w-0 items-start gap-3">
                    <ShieldAlert aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-red-300" />
                    <div className="min-w-0">
                        <h2 className="break-words text-xl font-semibold text-white">Borrar mi cuenta</h2>
                        <p className="mt-1 text-sm text-gray-400">
                            Es irreversible. Se eliminan la cartera, tesis, claims,
                            watchlist, alertas, documentos y sus originales, vectores de
                            búsqueda, sesiones y la propia cuenta. Exporta antes si quieres
                            conservar una copia.
                        </p>
                    </div>
                </div>

                <form className="mt-5 space-y-4" onSubmit={handleDelete}>
                    <div>
                        <Label className="block break-words leading-6" htmlFor="delete-confirmation">
                            Escribe <span className="block font-mono text-gray-200 [overflow-wrap:anywhere]">{email}</span> para confirmar
                        </Label>
                        <Input
                            autoComplete="off"
                            className="mt-2 min-h-11"
                            id="delete-confirmation"
                            name="confirmation"
                            onChange={(event) => setConfirmation(event.target.value)}
                            required
                            type="email"
                            value={confirmation}
                        />
                    </div>
                    <div>
                        <Label htmlFor="delete-password">Contraseña actual (reautenticación)</Label>
                        <Input
                            autoComplete="current-password"
                            className="mt-2 min-h-11"
                            id="delete-password"
                            name="password"
                            onChange={(event) => setPassword(event.target.value)}
                            required
                            type="password"
                            value={password}
                        />
                    </div>
                    <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2 text-sm leading-6 text-gray-300" htmlFor="delete-understood">
                        <input
                            checked={understood}
                            className="mt-0.5 size-5 shrink-0 accent-red-500"
                            id="delete-understood"
                            onChange={(event) => setUnderstood(event.target.checked)}
                            type="checkbox"
                        />
                        Entiendo que esta acción es irreversible y que no se puede deshacer.
                    </label>
                    <Button
                        className="w-full min-w-0 whitespace-normal text-left sm:w-auto"
                        disabled={deleting || !understood || !confirmation || !password}
                        type="submit"
                        variant="destructive"
                    >
                        {deleting ? 'Borrando cuenta…' : 'Borrar cuenta y todos mis datos'}
                    </Button>
                </form>
            </section>
        </div>
    );
}
