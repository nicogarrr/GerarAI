import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ThesisExportMenu from '@/components/research/ThesisExportMenu';

describe('Thesis export published and draft boundaries', () => {
    it('offers no export when neither a published version nor a draft exists', () => {
        const view = render(<ThesisExportMenu ticker="TEST" hasPublished={false} />);
        expect(view.container).toBeEmptyDOMElement();
        expect(screen.queryByRole('link')).not.toBeInTheDocument();
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });
    it('offers only the explicitly labeled draft PDF without published Markdown or reader', () => {
        render(<ThesisExportMenu ticker="A/B & C" hasPublished={false} latestDraftVersion={7} />);
        const link = screen.getByRole('link', { name: 'Descargar PDF (borrador v7)' });
        expect(link).toHaveAttribute('href', '/api/thesis/A%2FB%20%26%20C/pdf?draft=1');
        expect(link).toHaveAttribute('download');
        expect(link).toHaveAttribute('title', 'PDF de la v7 en borrador, sin veredicto ni cifras.');
        expect(screen.getAllByRole('link')).toHaveLength(1);
        expect(screen.queryByRole('button')).not.toBeInTheDocument();
        expect(screen.queryByText('Descargar Markdown')).not.toBeInTheDocument();
    });
    it.each([null, 9])('keeps published downloads published even with draft version %s', async latestDraftVersion => {
        render(<ThesisExportMenu ticker="A/B & C" hasPublished latestDraftVersion={latestDraftVersion} />);
        const pdf = screen.getByRole('link', { name: 'Descargar PDF' });
        expect(pdf).toHaveAttribute('href', '/api/thesis/A%2FB%20%26%20C/pdf');
        expect(pdf).toHaveAttribute('download');
        expect(pdf).not.toHaveAttribute('title');
        const trigger = screen.getByRole('button', { name: 'Leer / Descargar' });
        expect(trigger).toHaveAttribute('aria-expanded', 'false');
        fireEvent.keyDown(trigger, { key: 'ArrowDown' });
        const menu = await screen.findByRole('menu');
        expect(trigger).toHaveAttribute('aria-expanded', 'true');
        const read = within(menu).getByRole('menuitem', { name: 'Leer la tesis' });
        expect(read).toHaveAttribute('href', '/research/A%2FB%20%26%20C/tesis');
        expect(read).not.toHaveAttribute('download');
        const menuPdf = within(menu).getByRole('menuitem', { name: 'Descargar PDF' });
        expect(menuPdf).toHaveAttribute('href', '/api/thesis/A%2FB%20%26%20C/pdf');
        expect(menuPdf).toHaveAttribute('download');
        const md = within(menu).getByRole('menuitem', { name: 'Descargar Markdown' });
        expect(md).toHaveAttribute('href', '/api/thesis-memo/A%2FB%20%26%20C');
        expect(md).toHaveAttribute('download');
        expect(within(menu).getAllByRole('menuitem')).toHaveLength(3);
        expect(screen.queryByText(/borrador/)).not.toBeInTheDocument();
        fireEvent.keyDown(menu, { key: 'Escape' });
        expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        expect(trigger).toHaveAttribute('aria-expanded', 'false');
    });
});
