import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { library } = vi.hoisted(() => ({ library: vi.fn() }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: (name: string) => (name === 'gerarai_locale' ? { value: 'en' } : undefined) }) }));
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children, className }: { children: React.ReactNode; className?: string }) => <form className={className}>{children}</form> }));
vi.mock('@/components/forms/FileUploadInput', () => ({ FileUploadInput: () => null }));
vi.mock('@/components/knowledge/ExtractionRefresh', () => ({ ExtractionRefresh: () => null }));
vi.mock('@/components/knowledge/DeleteDocumentButton', () => ({ DeleteDocumentButton: () => null }));
vi.mock('@/components/knowledge/DeleteCollectionButton', () => ({ DeleteCollectionButton: () => null }));
vi.mock('@/app/(root)/inversores/_components/LibraryChat', () => ({ LibraryChat: () => null }));
vi.mock('@/components/research/ThesisMarkdown', () => ({ markdownComponents: {} }));
vi.mock('@/lib/actions/research-tools.actions', () => ({
  getKnowledgeLibrary: library, getKnowledgeDocument: vi.fn(async () => null), getKnowledgeDocumentChunks: vi.fn(async () => []),
  createKnowledgeCollectionResult: vi.fn(), decideKnowledgePrinciple: vi.fn(), extractKnowledgePrinciples: vi.fn(), installKnowledgeDefaults: vi.fn(),
  mergeKnowledgePrinciple: vi.fn(), reviseKnowledgePrincipleResult: vi.fn(), setKnowledgeDocumentTicker: vi.fn(), uploadKnowledgeDocumentResult: vi.fn(),
}));

import Knowledge from '@/app/(root)/knowledge/page';
import { ArchivedThesisNotice } from '@/components/knowledge/ArchivedThesisNotice';
import { createTranslator } from '@/lib/i18n/translate';

const doc = (id: number, title: string) => ({ id, title, author: null, ticker: null, collection_id: null, document_type: 'fund_letter', status: 'ready', publication_date: null, metadata: { parser: 'pypdf' } });
const base = { collections: [{ id: 7, name: 'Howard Marks' }], documentTotal: 1234, collectionCounts: { 7: 1 }, principles: [], principleTotal: 0, proposedTotal: 0, jobs: [] };

describe('Knowledge library in English', () => {
  beforeEach(() => library.mockReset());

  it('library tab: header, tabs, stats, table and search in English with English numbers', async () => {
    library.mockResolvedValue({ ...base, documents: [doc(1, 'Memo 2019')], documentSearch: { query: 'memo', total: 1 } });
    render(await Knowledge({ searchParams: Promise.resolve({ q: 'memo' }) }));
    expect(screen.getByText('Investment knowledge')).toBeTruthy();
    expect(screen.getAllByText('Library').length).toBeGreaterThan(0);
    expect(screen.getByText('Principles')).toBeTruthy();
    expect(screen.getByText('Pending approval')).toBeTruthy();
    expect(screen.getByText('1,234')).toBeTruthy();
    expect(screen.getByLabelText('Search the library')).toBeTruthy();
    expect(screen.getByText('1 document matches “memo”.')).toBeTruthy();
    const table = screen.getByRole('table');
    expect(within(table).getByText('Parser')).toBeTruthy();
    expect(within(table).getByText('Fund letter')).toBeTruthy();
    expect(within(table).getByText('Unknown author')).toBeTruthy();
    expect(within(table).getByText('ready')).toBeTruthy();
    expect(screen.getByText('· 1 document')).toBeTruthy();
    expect(screen.queryByText(/Biblioteca|Colecciones|Documentos|Extraer/)).toBeNull();
  });

  it('upload and principles tabs in English', async () => {
    library.mockResolvedValue({ ...base, documents: [], documentSearch: null });
    render(await Knowledge({ searchParams: Promise.resolve({ tab: 'subir' }) }));
    expect(screen.getByLabelText('Document language')).toBeTruthy();
    expect(screen.getByRole('option', { name: 'Personal postmortem' })).toBeTruthy();
    expect(screen.getByText('New collection')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Upload' })).toBeTruthy();
  });

  it('archived thesis notice follows the language', () => {
    render(<ArchivedThesisNotice documentType="own_thesis" t={createTranslator('en')} />);
    expect(screen.getByRole('note')).toHaveTextContent('Archived thesis: the original text of that version is kept');
  });
});
