import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GuideContextPanel } from '@/components/research/GuideContextPanel';
import { markBrainReady, OPEN_BRAIN_PENDING_KEY } from '@/lib/brain/open-brain';
import type { GuideContext } from '@/lib/research/assistant-contract';

beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => { markBrainReady(false); sessionStorage.clear(); });

const base: GuideContext = { ticker: 'ASTS', review_id: null, open_reviews: [], latest_news: [], missing_data: [] };

describe('GuideContextPanel', () => {
    it('avisa del fallo de carga cuando no hay contexto', () => {
        render(<GuideContextPanel ticker="ASTS" context={null} />);
        expect(screen.getByRole('status')).toHaveTextContent('No se pudo cargar el contexto de guía.');
    });
    it('estados vacíos: sin revisiones ni noticias', () => {
        render(<GuideContextPanel ticker="ASTS" context={base} />);
        expect(screen.getByText('Sin revisiones abiertas.')).toBeInTheDocument();
        expect(screen.getByText('Sin datos de noticias.')).toBeInTheDocument();
    });
    it('hideReviews oculta el bloque de revisiones pero mantiene las noticias', () => {
        const context: GuideContext = { ...base, open_reviews: [{ id: 7, status: 'open', summary: 'Revisar guía' }] };
        render(<GuideContextPanel ticker="ASTS" context={context} hideReviews />);
        expect(screen.queryByText('Revisiones abiertas')).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Preguntar al Cerebro' })).not.toBeInTheDocument();
        expect(screen.getByText('Últimas noticias atribuidas')).toBeInTheDocument();
    });
    it('abre el Cerebro anclado a la revisión al hacer clic', () => {
        markBrainReady(true);
        const listener = vi.fn();
        window.addEventListener('gerarai:open-brain', listener);
        const context: GuideContext = { ...base, open_reviews: [{ id: 7, status: 'open', summary: 'Revisar guía' }] };
        render(<GuideContextPanel ticker="ASTS" context={context} />);
        fireEvent.click(screen.getByRole('button', { name: 'Preguntar al Cerebro' }));
        expect(listener).toHaveBeenCalledOnce();
        expect((listener.mock.calls[0][0] as CustomEvent).detail).toEqual({ ticker: 'ASTS', review_id: 7 });
        expect(sessionStorage.getItem(OPEN_BRAIN_PENDING_KEY)).toBeNull();
        window.removeEventListener('gerarai:open-brain', listener);
    });
    it('las noticias con URL segura se enlazan y las inseguras quedan en texto plano', () => {
        const context: GuideContext = {
            ...base,
            latest_news: [
                { id: 1, title: 'Lanza un satélite', source: 'SEC', source_url: 'https://sec.gov/doc', date: '2026-10-01T10:00:00Z', date_source: 'source' },
                { id: 2, title: 'Noticia sin fuente', source: '', source_url: null, date: null, date_source: null },
                { id: 3, title: 'Enlace peligroso', source: 'Blog', source_url: 'javascript:alert(1)', date: '2026-10-02T00:00:00Z', date_source: 'gdelt_first_seen' },
            ],
        };
        render(<GuideContextPanel ticker="ASTS" context={context} />);
        expect(screen.getByRole('link', { name: 'Lanza un satélite' })).toHaveAttribute('href', 'https://sec.gov/doc');
        expect(screen.queryByRole('link', { name: 'Enlace peligroso' })).not.toBeInTheDocument();
        expect(screen.getByText('Enlace peligroso')).toBeInTheDocument();
        expect(screen.getByText(/Fuente sin datos/)).toBeInTheDocument();
        expect(screen.getByText(/Detectada/)).toBeInTheDocument();
    });
    it('lista los datos que faltan en el contexto', () => {
        const context: GuideContext = { ...base, missing_data: ['Sin precios históricos', 'Sin guía de ingresos'] };
        render(<GuideContextPanel ticker="ASTS" context={context} />);
        expect(screen.getByText('Datos que faltan en el contexto')).toBeInTheDocument();
        expect(screen.getByText('Sin precios históricos')).toBeInTheDocument();
        expect(screen.getByText('Sin guía de ingresos')).toBeInTheDocument();
    });
});
