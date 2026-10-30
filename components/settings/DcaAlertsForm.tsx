'use client';

import { useState } from 'react';
import { getFriendlyErrorMessage } from '@/lib/types/errors';
import { saveDcaAlertSettings, type DcaAlertSettings } from '@/lib/actions/dca-settings.actions';

export default function DcaAlertsForm({ initial }: { initial: DcaAlertSettings }) {
    const [up, setUp] = useState(initial.up_min_level);
    const [down, setDown] = useState(initial.down_max_level);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(initial);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    const save = async (event: React.FormEvent) => {
        event.preventDefault();
        setSaving(true); setError(''); setMessage('');
        try {
            const result = await saveDcaAlertSettings(up, down);
            setSaved(result);
            setMessage('Avisos DCA guardados para todas tus empresas. Los ajustes antiguos por empresa se conservan sin efecto.');
        } catch (err) { setError(getFriendlyErrorMessage(err)); }
        finally { setSaving(false); }
    };
    const options = [0, 1, 2, 3, 4];
    return <form onSubmit={save} className="space-y-4">
        <p className="text-sm text-gray-300">Un único ajuste para toda tu watchlist y cartera. No cambia el veredicto ni realiza órdenes.</p>
        <p className="text-xs text-gray-400">Valores activos: subida {saved.up_min_level ? `desde ${saved.up_min_level}X` : 'desactivada'}; bajada {saved.down_max_level ? `hasta ${saved.down_max_level}X` : 'desactivada'}. {saved.configured ? '' : 'Valores iniciales: 3X al subir y 1X al bajar.'}</p>
        {!saved.alerts_enabled ? <p role="status" className="text-sm text-amber-300">Los envíos de avisos están desactivados en el servidor. Guardar estos umbrales no los activa.</p> : null}
        <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm text-gray-200">Al subir, avisar desde
                <select value={up} onChange={(e) => setUp(Number(e.target.value))} disabled={saving} className="min-h-11 rounded border border-gray-600 bg-gray-900 px-3">
                    {options.map((v) => <option key={v} value={v}>{v ? `${v}X` : 'Desactivado'}</option>)}
                </select>
            </label>
            <label className="grid gap-2 text-sm text-gray-200">Al bajar, avisar hasta
                <select value={down} onChange={(e) => setDown(Number(e.target.value))} disabled={saving} className="min-h-11 rounded border border-gray-600 bg-gray-900 px-3">
                    {options.map((v) => <option key={v} value={v}>{v ? `${v}X` : 'Desactivado'}</option>)}
                </select>
            </label>
        </div>
        <p className="text-xs text-gray-400">Te avisamos solo cuando el nivel cambia y cruza tu umbral en la dirección elegida: al subir, si el nivel nuevo llega a tu umbral de subida o lo supera; al bajar, si cae a tu umbral de bajada o por debajo. Sin aviso en la primera evaluación ni si el nivel no cambia.</p>
        <p className="text-xs text-gray-400">Los recortes tienen su propio control en el servidor y no se modifican aquí. Los ajustes antiguos por empresa ({saved.legacy_override_count}) se conservan, pero no se aplican.</p>
        <button type="submit" disabled={saving} aria-busy={saving} className="min-h-11 rounded border border-teal-600 px-4 text-sm text-teal-300 disabled:opacity-50">{saving ? 'Guardando…' : 'Guardar avisos DCA'}</button>
        {message ? <p role="status" className="text-sm text-teal-300">{message}</p> : null}
        {error ? <p role="alert" className="text-sm text-red-300">{error}</p> : null}
    </form>;
}
