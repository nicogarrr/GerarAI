'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { saveDcaAlertSettings, type DcaAlertSettings } from '@/lib/actions/dca-settings.actions';
import { useT } from '@/lib/i18n/client';
import type { TranslateFn } from '@/lib/i18n/translate';
import { showErrorToast } from '@/lib/toast';

/** Solo se menciona si hay alguno: «(0) se conservan» describía algo que no existe. */
function legacyOverridesText(count: number, t: TranslateFn): string {
    return count === 1
        ? t('settings.dca.legacyOne')
        : t('settings.dca.legacyMany', { count });
}

export default function DcaAlertsForm({ initial }: { initial: DcaAlertSettings }) {
    const t = useT();
    const [up, setUp] = useState(initial.up_min_level);
    const [down, setDown] = useState(initial.down_max_level);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(initial);
    const save = async (event: React.FormEvent) => {
        event.preventDefault();
        setSaving(true);
        try {
            const result = await saveDcaAlertSettings(up, down);
            setSaved(result);
            // Toast como el resto de formularios de Ajustes (divisa, fiscal):
            // el aviso en linea bajo el boton quedaba lejos del foco en movil
            // y era el unico formulario de la pagina sin confirmacion flotante.
            toast.success(result.legacy_override_count > 0
                ? t('settings.dca.savedLegacy')
                : t('settings.dca.saved'));
        } catch (err) { showErrorToast(err); }
        finally { setSaving(false); }
    };
    const options = [0, 1, 2, 3, 4];
    return <form onSubmit={save} className="space-y-4">
        <p className="text-sm text-gray-300">{t('settings.dca.intro')}</p>
        <p className="text-xs text-gray-400">{t('settings.dca.activeValues', { up: saved.up_min_level ? t('settings.dca.fromLevel', { level: saved.up_min_level }) : t('settings.dca.disabledLower'), down: saved.down_max_level ? t('settings.dca.toLevel', { level: saved.down_max_level }) : t('settings.dca.disabledLower') })} {saved.configured ? '' : t('settings.dca.defaults')}</p>
        {!saved.alerts_enabled ? <p role="status" className="text-sm text-amber-300">{t('settings.dca.serverOff')}</p> : null}
        <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm text-gray-200">{t('settings.dca.upLabel')}
                <select value={up} onChange={(e) => setUp(Number(e.target.value))} disabled={saving} className="min-h-11 rounded border border-gray-600 bg-gray-900 px-3">
                    {options.map((v) => <option key={v} value={v}>{v ? `${v}X` : t('settings.dca.disabled')}</option>)}
                </select>
            </label>
            <label className="grid gap-2 text-sm text-gray-200">{t('settings.dca.downLabel')}
                <select value={down} onChange={(e) => setDown(Number(e.target.value))} disabled={saving} className="min-h-11 rounded border border-gray-600 bg-gray-900 px-3">
                    {options.map((v) => <option key={v} value={v}>{v ? `${v}X` : t('settings.dca.disabled')}</option>)}
                </select>
            </label>
        </div>
        <p className="text-xs text-gray-400">{t('settings.dca.rule')}</p>
        <p className="text-xs text-gray-400">{t('settings.dca.trims')}{saved.legacy_override_count > 0 ? ` ${legacyOverridesText(saved.legacy_override_count, t)}` : ''}</p>
        <button type="submit" disabled={saving} aria-busy={saving} className="min-h-11 rounded border border-teal-600 px-4 text-sm text-teal-300 disabled:opacity-50">{saving ? t('settings.common.saving') : t('settings.dca.submit')}</button>
    </form>;
}
