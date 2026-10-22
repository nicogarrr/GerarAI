import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { extractManagementCandidatesFromRegistry } from '@/lib/actions/research-tools.actions';

type RegistrySource = {
    url: string;
    period: string | null;
    call_date: string | null;
    label: string | null;
};

function safeUrl(url: string | null | undefined): string | null {
    if (!url) return null;
    return /^https:\/\//i.test(url) ? url : null;
}

function hostOf(url: string): string {
    try {
        return new URL(url).hostname;
    } catch {
        return url;
    }
}

/**
 * Extrae candidatos SOLO desde transcripciones ya registradas como fuente
 * oficial exacta de la empresa. La fecha de la llamada sale del registro,
 * no la introduce quien pulsa. Los candidatos nacen sin revisar: nada de
 * esto confirma un compromiso ni lo marca cumplido.
 */
export function ExtractFromRegistry({ ticker, sources }: { ticker: string; sources: RegistrySource[] | null }) {
    return (
        <section className="rounded-xl border border-gray-800 bg-surface-1 p-5">
            <h2 className="font-semibold text-gray-100">Extraer desde una transcripción registrada</h2>
            <p className="mt-1 text-xs text-gray-500">
                Solo documentos ya registrados como fuente oficial exacta de esta empresa; la fecha de la llamada sale del registro.
                Propone candidatos sin revisar: un candidato no es un compromiso confirmado y nada se marca cumplido sin evidencia.
            </p>
            {sources === null ? (
                <p className="mt-3 text-xs text-amber-300">No se pudo cargar el registro de fuentes. Esto no significa que no haya transcripciones registradas.</p>
            ) : sources.length === 0 ? (
                <p className="mt-3 text-xs text-gray-500">No hay transcripción oficial registrada para esta empresa.</p>
            ) : (
                <ul className="mt-4 grid gap-2">
                    {sources.map((src) => {
                        const url = safeUrl(src.url);
                        return (
                            <li className="flex flex-col gap-2 rounded-lg border border-gray-800 p-3 text-xs text-gray-400 sm:flex-row sm:items-center sm:justify-between" key={src.url}>
                                <div className="min-w-0">
                                    <span className="text-gray-300">{src.period ?? src.label ?? 'transcripción registrada'}</span>
                                    <span className="text-gray-500"> · {src.call_date ?? 'fecha no registrada'} · </span>
                                    {url ? (
                                        <a className="underline [overflow-wrap:anywhere]" href={url} rel="noopener noreferrer" target="_blank">{hostOf(url)}</a>
                                    ) : (
                                        <span className="text-amber-300">URL no verificable; no se puede extraer</span>
                                    )}
                                </div>
                                {url ? (
                                    <MutationForm action={extractManagementCandidatesFromRegistry.bind(null, ticker)} successMessage="Candidatos extraídos del registro (sin revisar)">
                                        <input name="source_url" type="hidden" value={url} />
                                        <Button className="w-full shrink-0 sm:w-auto" size="sm" type="submit" variant="ghost">Extraer candidatos</Button>
                                    </MutationForm>
                                ) : null}
                            </li>
                        );
                    })}
                </ul>
            )}
        </section>
    );
}
