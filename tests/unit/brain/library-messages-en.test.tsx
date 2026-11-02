import React from 'react';
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/link', () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));

import { BrainLibraryAnswer } from '@/components/brain/BrainLibraryAnswer';
import { LocaleProvider } from '@/lib/i18n/client';
import type { LibraryAnswer } from '@/lib/actions/knowledge-chat.actions';

// Frases reales del backend, leídas del .py: si cambian, el test lo nota.
const CHAT = readFileSync('data-engine/app/services/knowledge_chat.py', 'utf8');
const strings = (block: string) => [...block.matchAll(/"([^"]*)"/g)].map((m) => m[1]).join('');
const MESSAGES = [
    ...[...CHAT.matchAll(/message="([^"]+)"/g)].map((m) => m[1]),
    ...[...CHAT.matchAll(/"message": "([^"]+)"/g)].map((m) => m[1]),
    ...[...CHAT.matchAll(/result\["message"\] = \(\s*((?:"[^"]*"\s*)+)\)/g)].map((m) => strings(m[1])),
];
const ANALYSIS = readFileSync('data-engine/app/services/knowledge_analysis.py', 'utf8');
const DISCLAIMER = ANALYSIS.match(/DISCLAIMER = "([^"]+)"/)![1];
const PROBABILITIES = ANALYSIS.match(/"probabilidades": "([^"]+)"/)![1];

const answer = (message: string | null, extra: Partial<LibraryAnswer> = {}): LibraryAnswer => ({
    status: 'fragmentos', kind: 'doctrina', retrieval: 'vector', message, answers: [], ...extra,
});

function show(result: LibraryAnswer, locale: 'es' | 'en') {
    return render(<LocaleProvider locale={locale}><BrainLibraryAnswer result={result} /></LocaleProvider>);
}

describe('Biblioteca: avisos del backend en el idioma de la pantalla', () => {
    it('lee los 7 avisos y el descargo del backend', () => {
        expect(MESSAGES).toHaveLength(7);
        expect(new Set(MESSAGES).size).toBe(7);
        expect(DISCLAIMER).toMatch(/^No es consejo financiero/);
    });

    it.each(MESSAGES)('en inglés, sin castellano: %s', (message) => {
        const { container, unmount } = show(answer(message), 'en');
        expect(container.textContent).not.toMatch(/Fragmentos|fragmentos|biblioteca|disponible|pregunta/);
        expect(container.textContent).toMatch(/[Pp]assages|analysis/);
        unmount();
    });

    it.each(MESSAGES)('en castellano, tal cual: %s', (message) => {
        const { unmount } = show(answer(message), 'es');
        expect(screen.getByText(message)).toBeTruthy();
        unmount();
    });

    it('el descargo y la nota de probabilidades del análisis salen en inglés', () => {
        const citation = { chunk_id: 1, document_id: 1, title: 'Carta 1987', author: 'Buffett', page_number: null, chunk_index: 0, quote: 'Cita', source_url: null, publication_date: null, document_type: 'fund_letter' };
        const analysis = { tesis: [], error: { text: 'Error', citation }, escenarios: [], modelos: [], no_se: [], probabilidades: PROBABILITIES, aviso: DISCLAIMER };
        show(answer(null, { status: 'ok', analysis }), 'en');
        expect(screen.getByText('Not financial advice. Library doctrine, not current company data.')).toBeTruthy();
        expect(screen.getByText('Model estimate, not a data point.')).toBeTruthy();
    });

    it('un texto distinto pasa tal cual', () => {
        show(answer('Otro aviso'), 'en');
        expect(screen.getByText('Otro aviso')).toBeTruthy();
    });
});
