import { beforeEach, describe, expect, it, vi } from 'vitest';

// El store es estado de módulo (owner único del buscador): cada test importa
// una copia fresca para no arrastrar instancias ni listeners.
async function freshStore() {
    vi.resetModules();
    return import('@/lib/search/search-command-store');
}

function instance(id: string, visible = true) {
    return {
        id,
        isTriggerVisible: () => visible,
        captureReturnFocus: vi.fn(),
    };
}

beforeEach(() => {
    vi.restoreAllMocks();
});

describe('search-command-store: owner único', () => {
    it('abrir fija owner y captura el foco de retorno; cerrar mantiene owner sticky (animación)', async () => {
        const store = await freshStore();
        const a = instance('desktop');
        store.registerSearchCommandInstance(a);
        store.openSearchCommand('desktop');
        expect(a.captureReturnFocus).toHaveBeenCalledTimes(1);
        expect(store.getSearchCommandSnapshot()).toEqual({ open: true, ownerId: 'desktop' });
        store.closeSearchCommand();
        expect(store.getSearchCommandSnapshot()).toEqual({ open: false, ownerId: 'desktop' });
    });

    it('subscribe notifica y se puede dar de baja', async () => {
        const store = await freshStore();
        store.registerSearchCommandInstance(instance('a'));
        const listener = vi.fn();
        const off = store.subscribeSearchCommand(listener);
        store.openSearchCommand('a');
        store.closeSearchCommand();
        expect(listener).toHaveBeenCalledTimes(2);
        off();
        store.openSearchCommand('a');
        expect(listener).toHaveBeenCalledTimes(2);
    });

    it('si la dueña se desmonta con el diálogo abierto, el store cierra (sin owner huérfano)', async () => {
        const store = await freshStore();
        const off = store.registerSearchCommandInstance(instance('drawer'));
        store.openSearchCommand('drawer');
        off();
        expect(store.getSearchCommandSnapshot()).toEqual({ open: false, ownerId: null });
    });

    it('cerrar sin abrir no hace nada', async () => {
        const store = await freshStore();
        const listener = vi.fn();
        store.subscribeSearchCommand(listener);
        store.closeSearchCommand();
        expect(listener).not.toHaveBeenCalled();
    });
});

describe('search-command-store: atajos de teclado', () => {
    it('Ctrl+K abre la instancia cuyo gatillo está visible y vuelve a cerrar al repetir', async () => {
        const store = await freshStore();
        store.registerSearchCommandInstance(instance('desktop', false));
        store.registerSearchCommandInstance(instance('movil', true));
        store.ensureSearchCommandShortcutListener();
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
        expect(store.getSearchCommandSnapshot()).toEqual({ open: true, ownerId: 'movil' });
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
        expect(store.getSearchCommandSnapshot().open).toBe(false);
    });

    it('Ctrl+K con ningún gatillo visible usa la primera instancia registrada', async () => {
        const store = await freshStore();
        store.registerSearchCommandInstance(instance('primera', false));
        store.registerSearchCommandInstance(instance('segunda', false));
        store.ensureSearchCommandShortcutListener();
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'K', metaKey: true, cancelable: true }));
        expect(store.getSearchCommandSnapshot().ownerId).toBe('primera');
    });

    it('«/» abre el buscador salvo dentro de inputs, textarea o contentEditable', async () => {
        const store = await freshStore();
        store.registerSearchCommandInstance(instance('a'));
        store.ensureSearchCommandShortcutListener();
        const input = document.createElement('input');
        document.body.appendChild(input);
        input.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true }));
        expect(store.getSearchCommandSnapshot().open).toBe(false);
        window.dispatchEvent(new KeyboardEvent('keydown', { key: '/', cancelable: true }));
        expect(store.getSearchCommandSnapshot().open).toBe(true);
        input.remove();
    });

    it('instalar el listener dos veces no duplica toggles', async () => {
        const store = await freshStore();
        store.registerSearchCommandInstance(instance('a'));
        store.ensureSearchCommandShortcutListener();
        store.ensureSearchCommandShortcutListener();
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, cancelable: true }));
        expect(store.getSearchCommandSnapshot().open).toBe(true); // una sola apertura, no toggle-toggle
    });
});
