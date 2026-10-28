import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { MemoPage } from '@/lib/research/memo-pages';
const mocks = vi.hoisted(() => ({ loading: null as null | (() => ReactNode) }));
vi.mock('next/dynamic', () => ({ default: (_loader: unknown, options: { loading: () => ReactNode }) => {
    mocks.loading = options.loading;
    return ({ content }: { content: string }) => <div data-testid="memo-body">{content}</div>;
} }));
import ThesisMarkdownPager from '@/components/research/ThesisMarkdownPager';
const pages: MemoPage[] = [
    { id: 'one', title: 'Primera', body: 'Contenido uno' },
    { id: 'two', title: 'Segunda', body: 'Contenido dos' },
    { id: 'three', title: 'Tercera', body: 'Contenido tres' },
];
afterEach(() => vi.restoreAllMocks());

describe('Memo pager section navigation', () => {
    it('provides an aria-hidden skeleton while the Markdown renderer loads', () => {
        const Loading = mocks.loading!; const view = render(<Loading />);
        expect(view.container.firstElementChild).toHaveAttribute('aria-hidden', 'true');
        expect(view.container.querySelectorAll('.animate-pulse')).toHaveLength(3);
    });
    it('renders nothing for an empty memo', () => {
        const view = render(<ThesisMarkdownPager pages={[]} />); expect(view.container).toBeEmptyDOMElement();
    });
    it('shows one section at a time with accessible selector and disabled boundary controls', () => {
        render(<ThesisMarkdownPager pages={pages} />);
        expect(screen.getByTestId('memo-body')).toHaveTextContent('Contenido uno');
        expect(screen.getByRole('combobox', { name: 'Sección del memorando' })).toHaveValue('0');
        expect(screen.getAllByRole('option').map(option => option.textContent)).toEqual(['1. Primera', '2. Segunda', '3. Tercera']);
        expect(screen.getByRole('button', { name: 'Sección anterior' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Anterior', exact: true })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Sección siguiente' }));
        expect(screen.getByTestId('memo-body')).toHaveTextContent('Contenido dos'); expect(screen.getByText('2/3')).toBeVisible();
        fireEvent.click(screen.getByRole('button', { name: 'Siguiente', exact: true }));
        expect(screen.getByTestId('memo-body')).toHaveTextContent('Contenido tres');
        expect(screen.getByRole('button', { name: 'Sección siguiente' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Siguiente', exact: true })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: 'Sección anterior' }));
        fireEvent.click(screen.getByRole('button', { name: 'Anterior', exact: true }));
        expect(screen.getByText('1/3')).toBeVisible();
        fireEvent.change(screen.getByRole('combobox'), { target: { value: '2' } });
        expect(screen.getByTestId('memo-body')).toHaveTextContent('Contenido tres');
        expect(screen.queryByText('Contenido uno')).not.toBeInTheDocument();
    });
    it('scrolls only if the memo header is above the viewport', () => {
        const bounds = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ top: -20 } as DOMRect);
        const scroll = vi.fn();
        const oldScroll = Element.prototype.scrollIntoView;
        Element.prototype.scrollIntoView = scroll;
        try {
            render(<ThesisMarkdownPager pages={pages} />);
            fireEvent.click(screen.getByRole('button', { name: 'Sección siguiente' }));
            expect(scroll).toHaveBeenCalledWith({ block: 'start' }); expect(scroll).toHaveBeenCalledOnce();
            bounds.mockReturnValue({ top: 0 } as DOMRect);
            fireEvent.click(screen.getByRole('button', { name: 'Sección anterior' }));
            expect(scroll).toHaveBeenCalledOnce();
        } finally { Element.prototype.scrollIntoView = oldScroll; vi.unstubAllGlobals(); }
    });
    it('clamps the selected section when a shorter memo arrives and handles a single section', () => {
        const view = render(<ThesisMarkdownPager pages={pages} />);
        fireEvent.change(screen.getByRole('combobox'), { target: { value: '2' } });
        view.rerender(<ThesisMarkdownPager pages={[pages[0]]} />);
        expect(screen.getByTestId('memo-body')).toHaveTextContent('Contenido uno');
        expect(screen.getByText('1/1')).toBeVisible();
        for (const button of screen.getAllByRole('button')) expect(button).toBeDisabled();
    });
});
