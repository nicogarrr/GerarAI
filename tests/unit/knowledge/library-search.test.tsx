import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { library } = vi.hoisted(() => ({ library: vi.fn() }));
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children, className }: { children: React.ReactNode; className?: string }) => <form className={className}>{children}</form> }));
vi.mock('@/components/forms/FileUploadInput', () => ({ FileUploadInput: () => null }));
vi.mock('@/components/knowledge/ExtractionRefresh', () => ({ ExtractionRefresh: () => null }));
vi.mock('@/components/knowledge/DeleteDocumentButton', () => ({ DeleteDocumentButton: () => null }));
vi.mock('@/components/knowledge/DeleteCollectionButton', () => ({ DeleteCollectionButton: () => null }));
vi.mock('@/app/(root)/inversores/_components/LibraryChat', () => ({ LibraryChat: () => null }));
vi.mock('@/components/research/ThesisMarkdown', () => ({ markdownComponents: {} }));
vi.mock('@/lib/actions/research-tools.actions', () => ({
  getKnowledgeLibrary: library, getKnowledgeDocument: vi.fn(async () => null), getKnowledgeDocumentChunks: vi.fn(async () => []),
  createKnowledgeCollection: vi.fn(), decideKnowledgePrinciple: vi.fn(), extractKnowledgePrinciples: vi.fn(), installKnowledgeDefaults: vi.fn(),
  mergeKnowledgePrinciple: vi.fn(), reviseKnowledgePrinciple: vi.fn(), setKnowledgeDocumentTicker: vi.fn(), uploadKnowledgeDocument: vi.fn(),
}));

import Knowledge from '@/app/(root)/knowledge/page';

const doc = (id: number, title: string) => ({ id, title, author: 'Warren Buffett', ticker: null, collection_id: null, document_type: 'investor_letter', status: 'ready', publication_date: null, metadata: {} });
const base = { collections: [], documentTotal: 120, collectionCounts: {}, principles: [], principleTotal: 0, proposedTotal: 0, jobs: [] };

// Biblioteca (30-oct): no había forma de buscar un documento dentro de la
// biblioteca; sólo «Buscar en todo» (/search, texto completo). Ahora un ?q=
// se busca en el backend por título, autor o ticker y la lista lo respeta.
describe('Biblioteca: buscador', () => {
  beforeEach(() => library.mockReset());

  it('sin búsqueda muestra el buscador vacío y pide la lista normal', async () => {
    library.mockResolvedValue({ ...base, documents: [doc(1, 'Carta 2019')], documentSearch: null });
    render(await Knowledge({ searchParams: Promise.resolve({}) }));
    const input = screen.getByLabelText('Buscar en la biblioteca') as HTMLInputElement;
    expect(input.name).toBe('q');
    expect(input.value).toBe('');
    expect(input.closest('form')?.getAttribute('action')).toBe('/knowledge');
    expect(input.closest('form')?.getAttribute('method')).toBe('get');
    expect(library).toHaveBeenCalledWith(expect.objectContaining({ q: '' }));
    expect(screen.queryByText('Quitar búsqueda')).toBeNull();
  });

  it('con ?q= pide la búsqueda al backend, cuenta resultados y conserva la búsqueda al abrir y paginar', async () => {
    library.mockResolvedValue({ ...base, documents: Array.from({ length: 50 }, (_, i) => doc(i + 1, `Carta ${i + 1}`)), documentSearch: { query: 'buffett', total: 73 } });
    render(await Knowledge({ searchParams: Promise.resolve({ q: '  buffett  ' }) }));
    expect(library).toHaveBeenCalledWith(expect.objectContaining({ q: 'buffett' }));
    expect((screen.getByLabelText('Buscar en la biblioteca') as HTMLInputElement).value).toBe('buffett');
    expect(screen.getByText('73 documentos coinciden con «buffett».')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Quitar búsqueda' }).getAttribute('href')).toBe('/knowledge#documentos');
    const reader = screen.getAllByRole('link', { name: 'Carta 1' })[0];
    expect(reader.getAttribute('href')).toBe('/knowledge?document=1&q=buffett#fragmentos');
    const pager = screen.getAllByRole('navigation', { name: 'Páginas de documentos' })[0];
    expect(within(pager).getByText('1-50 de 73')).toBeTruthy();
    expect(within(pager).getByRole('link', { name: 'Siguientes' }).getAttribute('href')).toBe('/knowledge?tab=biblioteca&documentOffset=50&q=buffett');
  });

  it('sin coincidencias no invita a subir el primer documento y ofrece buscar en el texto', async () => {
    library.mockResolvedValue({ ...base, documents: [], documentSearch: { query: 'zzz', total: 0 } });
    render(await Knowledge({ searchParams: Promise.resolve({ q: 'zzz' }) }));
    expect(screen.getByText(/Ningún documento coincide con «zzz»/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Buscar «zzz» dentro del texto' }).getAttribute('href')).toBe('/search?q=zzz');
    expect(screen.queryByText('No hay documentos en esta página.')).toBeNull();
  });
});
