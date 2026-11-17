'use client';

import { useState } from 'react';
import { useT } from '@/lib/i18n/client';
import { readBrainChatModel, writeBrainChatModel, type BrainChatModel } from '@/lib/brain/chat-model';

/**
 * Preferencia "Modelo del chat general" del Cerebro (Ajustes > LLM).
 * Local del navegador: el panel la lee al abrirse (lib/brain/chat-model).
 */
export default function BrainChatModelForm() {
    const t = useT();
    const [model, setModel] = useState<BrainChatModel>(() => readBrainChatModel(globalThis.localStorage));
    const choose = (value: string) => {
        const next: BrainChatModel = value === 'hy4-flash-free' ? 'hy4-flash-free' : '';
        setModel(next);
        writeBrainChatModel(globalThis.localStorage, next);
    };
    return (
        <label className="flex flex-col gap-1 text-sm text-gray-300">
            {t('settings.llm.chatModelLabel')}
            <select
                aria-label={t('settings.llm.chatModelLabel')}
                value={model}
                onChange={(e) => choose(e.target.value)}
                className="min-h-11 w-64 max-w-full rounded border border-gray-700 bg-gray-950 px-3 text-sm text-gray-200"
            >
                <option value="">{t('settings.llm.chatModelDefault')}</option>
                <option value="hy4-flash-free">{t('settings.llm.chatModelHy4')}</option>
            </select>
        </label>
    );
}
