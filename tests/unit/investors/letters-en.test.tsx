import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en', document: vi.fn(), chunks: vi.fn(), letters: vi.fn() }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('next/navigation', () => ({ notFound: () => { throw Error('NOT_FOUND'); }, usePathname: () => '/inversores/cartas' }));
vi.mock('next/link', () => ({ default: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a> }));
vi.mock('@/lib/actions/research-tools.actions', () => ({
    getKnowledgeDocument: mocks.document,
    getKnowledgeDocumentChunkPage: mocks.chunks,
    getKnowledgeLetters: mocks.letters,
    ingestLettersCorpusNow: vi.fn().mockResolvedValue({ success: false }),
}));
vi.mock('@/app/(root)/inversores/_components/LibraryChat', () => ({ LibraryChat: ({ label }: { label: string }) => <span>{label}</span> }));
vi.mock('@/app/(root)/inversores/_components/Pagination', () => ({ Pagination: () => null, paginate: <T,>(items: T[]) => ({ items, page: 1, total: 1 }) }));
vi.mock('@/components/system/BackendOffline', () => ({ default: () => null }));

import LettersPage from '@/app/(root)/inversores/cartas/page';
import LetterReaderPage from '@/app/(root)/inversores/cartas/[id]/page';
import { IngestLettersButton } from '@/app/(root)/inversores/_components/IngestLettersButton';
import { InvestorLetters } from '@/app/(root)/inversores/_components/InvestorLetters';
import { LocaleProvider } from '@/lib/i18n/client';

const letter = (id: number, title: string, author: string | null, extra: Record<string, unknown> = {}) => ({
    id, title, author, document_type: 'fund_letter', status: 'ready', publication_date: null, source_url: null, chunk_count: 0, ...extra,
});

describe('Cartas de inversores en inglés', () => {
    it('la lista de cartas sale en inglés, también el grupo sin autor', async () => {
        mocks.locale = 'en';
        mocks.letters.mockResolvedValue([letter(1, 'Carta 1977', null), letter(2, 'Otra 2001', null, { source_url: 'https://x.test/a.pdf' })]);
        render(await LettersPage({ searchParams: Promise.resolve({}) }));
        expect(screen.getByRole('heading', { level: 1, name: 'Letters' })).toBeTruthy();
        expect(screen.getByText('Back to investors')).toBeTruthy();
        expect(screen.getByText('No author · 2 letters')).toBeTruthy();
        expect(screen.getAllByText('Read')).toHaveLength(2);
        expect(screen.getByText('Original PDF')).toBeTruthy();
        expect(screen.getByText('No original PDF')).toBeTruthy();
        expect(screen.getByText(/Publication date not recorded · the title says 1977/)).toBeTruthy();
        expect(screen.getByText(/^Source: GerarAI library\./)).toBeTruthy();
    });

    it('la biblioteca vacía sale en inglés y en español no cambia', async () => {
        mocks.letters.mockResolvedValue([]);
        mocks.locale = 'en';
        const en = render(<LocaleProvider locale="en">{await LettersPage({ searchParams: Promise.resolve({}) })}</LocaleProvider>);
        expect(screen.getByText('There are no letters in the library yet.')).toBeTruthy();
        expect(screen.getByRole('button', { name: /Download free letters/ })).toBeTruthy();
        en.unmount();
        mocks.locale = 'es';
        render(<LocaleProvider locale="es">{await LettersPage({ searchParams: Promise.resolve({}) })}</LocaleProvider>);
        expect(screen.getByText('Todavía no hay cartas en la biblioteca.')).toBeTruthy();
        expect(screen.getByRole('button', { name: /Descargar cartas gratuitas/ })).toBeTruthy();
    });

    it('el lector de una carta sale en inglés', async () => {
        mocks.locale = 'en';
        mocks.letters.mockResolvedValue([]);
        mocks.document.mockResolvedValue(letter(987, 'Letter 2031', 'Warren Buffett', { chunk_count: 1, publication_date: '2031-02-27' }));
        mocks.chunks.mockResolvedValue([{ id: 5, chunk_index: 0, page_number: 3, content: 'Texto' }]);
        render(await LetterReaderPage({ params: Promise.resolve({ id: '987' }), searchParams: Promise.resolve({}) }));
        expect(screen.getByText("Back to Warren Buffett's letters")).toBeTruthy();
        expect(screen.getByText(/Published 2031-02-27/)).toBeTruthy();
        expect(screen.getByText('Ask about this letter')).toBeTruthy();
        expect(screen.getByRole('region', { name: 'Letter text' })).toBeTruthy();
        expect(screen.getByText(/Excerpt 1/).textContent).toBe('Excerpt 1 · page 3');
    });

    it('el botón de descarga muestra su error en inglés', async () => {
        render(<LocaleProvider locale="en"><IngestLettersButton /></LocaleProvider>);
        screen.getByRole('button', { name: /Download free letters/ }).click();
        expect(await screen.findByText("Couldn't queue the download. Try again.")).toBeTruthy();
    });

    it('las cartas de la ficha del inversor salen en inglés', async () => {
        mocks.locale = 'en';
        render(await InvestorLetters({ slug: 'buffett', documents: [], publicLetters: [{ title: 'Shareholder letters', date: '', url: 'https://x.test' }] }));
        expect(screen.getByRole('heading', { name: 'Letters' })).toBeTruthy();
        expect(screen.getByText('N/A · No indexed letters from this investor')).toBeTruthy();
        expect(screen.getByText('Sources about the investor')).toBeTruthy();
        expect(screen.getByText('Shareholder letters · Original source')).toBeTruthy();
    });
});
