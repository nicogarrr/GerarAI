import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { BRAIN_CHAT_MODEL_KEY } from '@/lib/brain/chat-model';
import BrainChatModelForm from '@/components/settings/BrainChatModelForm';

vi.mock('next/navigation', () => ({ usePathname: () => '/settings' }));

const show = () => render(<LocaleProvider locale="es"><BrainChatModelForm /></LocaleProvider>);

beforeEach(() => {
    window.localStorage.clear();
});

describe('Ajustes > LLM: preferencia "Modelo del chat general"', () => {
    it('arranca en el modelo por defecto y guarda la elección en local', () => {
        show();
        const select = screen.getByRole('combobox', { name: 'Modelo del chat general' });
        expect(select).toHaveValue('');
        fireEvent.change(select, { target: { value: 'hy4-flash-free' } });
        expect(window.localStorage.getItem(BRAIN_CHAT_MODEL_KEY)).toBe('hy4-flash-free');
        expect(select).toHaveValue('hy4-flash-free');
    });

    it('volver al defecto borra la clave', () => {
        window.localStorage.setItem(BRAIN_CHAT_MODEL_KEY, 'hy4-flash-free');
        show();
        const select = screen.getByRole('combobox', { name: 'Modelo del chat general' });
        expect(select).toHaveValue('hy4-flash-free');
        fireEvent.change(select, { target: { value: '' } });
        expect(window.localStorage.getItem(BRAIN_CHAT_MODEL_KEY)).toBeNull();
    });

    it('ignora valores ajenos en el select', () => {
        show();
        const select = screen.getByRole('combobox', { name: 'Modelo del chat general' });
        fireEvent.change(select, { target: { value: 'otro-modelo' } });
        expect(select).toHaveValue('');
        expect(window.localStorage.getItem(BRAIN_CHAT_MODEL_KEY)).toBeNull();
    });
});
