import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children, className }: {children: React.ReactNode; className?: string}) => <form className={className}>{children}</form> }));
vi.mock('@/lib/actions/finnhub.actions', () => ({ searchStocksWithStatus: vi.fn(async () => ({status: 'ok', stocks: []})) }));
vi.mock('@/components/knowledge/ExtractionRefresh', () => ({ ExtractionRefresh: () => null }));
vi.mock('@/app/(root)/inversores/_components/LibraryChat', () => ({ LibraryChat: () => null }));
vi.mock('@/components/research/NewsEventsFlow', () => ({ NewsEventsFlow: () => null }));
vi.mock('@/components/research/ThesisMarkdown', () => ({ markdownComponents: {} }));
vi.mock('@/lib/actions/research-tools.actions', () => ({
  createDriverAssumption: vi.fn(), getDriverAssumptions: vi.fn(async () => []),
  getFinancialTerminal: vi.fn(async () => ({ coverage: {percent: 0, available: 0, requested: 0}, metrics: [], periodicity: 'annual' })),
  createManagementPromise: vi.fn(), importManagementCallClaims: vi.fn(), reconcileManagementCredibility: vi.fn(), updateManagementExplanation: vi.fn(),
  getManagementCredibility: vi.fn(async () => ({ score: null, grade: 'insufficient_history', counts: {}, method: '', promises: [{id: 17, promise: 'Promesa sintética', promise_date: '2026-10-01', expected_period: 'FY2027', status: 'open'}] })),
  getKnowledgeGraph: vi.fn(async () => ({nodes: [], edges: [], node_count: 0, edge_count: 0})), getKnowledgeNeighborhood: vi.fn(), syncKnowledgeGraph: vi.fn(),
  getKnowledgeLibrary: vi.fn(async () => ({collections: [], documents: [], principles: [], jobs: []})), getKnowledgeDocumentChunks: vi.fn(),
  createKnowledgeCollection: vi.fn(), decideKnowledgePrinciple: vi.fn(), extractKnowledgePrinciples: vi.fn(), installKnowledgeDefaults: vi.fn(), mergeKnowledgePrinciple: vi.fn(), reviseKnowledgePrinciple: vi.fn(), setKnowledgeDocumentTicker: vi.fn(), uploadKnowledgeDocument: vi.fn(), searchResearchLibrary: vi.fn(),
}));
vi.mock('@/lib/actions/research.actions', () => ({getResearchNews: vi.fn(async () => []), analyzeManualNews: vi.fn(), ingestResearchNewsFeed: vi.fn()}));
vi.mock('@/lib/actions/ticker-context.actions', () => ({getTickerContext: vi.fn(async () => ({portfolioTickers: [], watchlistTickers: []}))}));

import Search from '@/app/(root)/search/page';
import { FinancialTerminalSection } from '@/components/research/sections/FinancialTerminalSection';
import { ManagementCredibilitySection } from '@/components/research/sections/ManagementCredibilitySection';
import { DriverAssumptionsSection } from '@/components/research/sections/DriverAssumptionsSection';
import { getFinancialTerminal, getManagementCredibility, getDriverAssumptions } from '@/lib/actions/research-tools.actions';
import Knowledge from '@/app/(root)/knowledge/page';
import Graph from '@/app/(root)/knowledge-graph/page';
import News from '@/app/(root)/research/news/page';

const params = Promise.resolve({ticker: 'DEMO'});
const searchParams = Promise.resolve({});
const cases = [
 ['search', () => Search({searchParams}), {'Buscar en el research':'q', 'Tipos de entidad':'entity_types','Tipos de fuente':'source_types','Estados':'statuses','ID de colección':'collection_id','Fecha desde':'date_from','Fecha hasta':'date_to','Tipo de búsqueda':'vector'}],
 // Terminal, directiva y drivers son secciones de la ficha desde el
 // 29-oct-2026 («Una fila, no tres menús»): se renderizan con sus datos.
 ['terminal', async () => <FinancialTerminalSection metrics={undefined} periodicity="annual" terminal={await getFinancialTerminal('DEMO')} years={10} />, {'Métricas':'metrics','Años de historial (1-20)':'years','Periodicidad':'periodicity'}],
 ['management', async () => <ManagementCredibilitySection dashboard={await getManagementCredibility('DEMO')} ticker="DEMO" />, {'Promesa de la directiva':'promise','Fecha de la promesa':'promise_date','Periodo esperado':'expected_period','Métrica canónica (opcional)':'metric','Comparación con el objetivo':'operator','Valor objetivo (opcional)':'target_value','Unidad (opcional)':'unit','ID del documento fuente (opcional)':'source_document_id','Explicación de la directiva o contexto del analista':'explanation'}],
 ['drivers', async () => <DriverAssumptionsSection assumptions={await getDriverAssumptions('DEMO')} ticker="DEMO" />, {'Clave del driver':'driver_key','Año fiscal':'fiscal_year','Escenario':'scenario','Valor':'value','Confianza (0-1)':'confidence','Fuente o ajuste del analista':'source','Justificación':'rationale'}],
 ['knowledge', () => Knowledge({searchParams}), {'Nombre de la colección':'name','Tipo de colección':'collection_type','Descripción (opcional)':'description'}],
 ['graph', () => Graph({searchParams}), {'Tipos de nodo':'node_types'}],
 ['news', () => News({searchParams}), {'Noticias del lote (JSON)':'items'}],
] as const;

describe('persistent visible labels in research forms', () => {
 for (const [name, page, labels] of cases) it(`${name}: associates labels and preserves form field names`, async () => {
   render(await page());
   for (const [label, field] of Object.entries(labels)) {
     const control = screen.getByLabelText(label, {exact: true});
     expect(control).toHaveAttribute('name', field);
     expect(control.closest('label')).not.toHaveClass('sr-only');
     expect(control.closest('label')?.querySelector('span')).toHaveTextContent(label);
   }
   // Visual QA uses rendered real forms with mocked reads; no production writes.

 });
});
