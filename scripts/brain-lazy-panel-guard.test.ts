/**
 * Guard de rendimiento: el panel del cerebro (chat, guía y biblioteca, con
 * react-markdown ya diferido dentro) no puede viajar en el bundle inicial del
 * layout autenticado: está montado en TODAS las páginas y el panel pasa la
 * mayor parte del tiempo cerrado. El shell (gatillo, oyentes de apertura y
 * estado de la conversación) queda eager; el panel carga con next/dynamic.
 *
 * Ejecución: node --experimental-strip-types --test scripts/brain-lazy-panel-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const shell = readFileSync('components/brain/GlobalBrain.tsx', 'utf8');
const panel = readFileSync('components/brain/GlobalBrainPanel.tsx', 'utf8');

describe('cerebro: panel diferido fuera del bundle inicial', () => {
    it('el shell no importa el panel ni el chat en estático', () => {
        assert.ok(!/import\s+\{?\s*GlobalBrainPanel\s*\}?\s+from\s+'\.\/GlobalBrainPanel';/.test(shell), 'sin import estático del panel');
        assert.ok(!/chatWithPortfolio|askKnowledge|askResearchAssistantAction|TickerSearchInput/.test(shell.replace(/import type[\s\S]*?from '\.\/GlobalBrainPanel';/, '')), 'el shell no arrastra las acciones del chat');
        assert.match(shell, /dynamic\(\(\) => loadBrainPanel\(\)\.then\(\(mod\) => mod\.GlobalBrainPanel\)/);
    });

    it('el gatillo precarga el chunk antes del click y los handoffs también', () => {
        assert.match(shell, /onPointerDown=\{\(\) => void loadBrainPanel\(\)\}/);
        assert.match(shell, /onFocus=\{\(\) => void loadBrainPanel\(\)\}/);
        assert.match(shell, /function openWithDetail[\s\S]{0,320}void loadBrainPanel\(\);/);
    });

    it('la conversación sobrevive a cerrar el panel (estado en el shell)', () => {
        assert.match(shell, /const \[messages, setMessages\] = useState<BrainMessage\[\]>/);
        assert.match(shell, /restoreConversation/);
        assert.match(shell, /serializeConversation/);
        assert.match(panel, /setMessages: React\.Dispatch<React\.SetStateAction<BrainMessage\[\]>>/);
    });

    it('los oyentes de apertura (evento, sessionStorage, slot) viven en el shell siempre montado', () => {
        assert.match(shell, /window\.addEventListener\('gerarai:open-brain'/);
        assert.match(shell, /OPEN_BRAIN_PENDING_KEY/);
        assert.match(shell, /getElementById\('brain-library-slot'\)/);
        assert.ok(!panel.includes("addEventListener('gerarai:open-brain'"), 'el panel no duplica oyentes');
    });

    it('el fallback de carga no desplaza el layout (posición fija del panel)', () => {
        assert.match(shell, /role="status"/);
        assert.match(shell, /aria-label="Cargando el cerebro"/);
        assert.match(shell, /fixed z-50/);
    });

    it('el panel conserva el cierre y el foco modal', () => {
        assert.match(panel, /onClose\(\)/);
        assert.match(panel, /aria-modal=\{librarySlot \? undefined : true\}/);
        assert.match(panel, /role=\{librarySlot \? "region" : "dialog"\}/);
    });
});
