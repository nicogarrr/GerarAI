import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { CompanyHeaderQuoteSkeleton } from '@/components/research/CompanyHeaderQuoteSkeleton';

// La reserva compacta replica la variante compacta de CompanyHeaderQuote
// (vistas secundarias de la ficha): sin tira de métricas ni hueco de gráfico,
// que la variante real nunca pinta. Una reserva más alta que el contenido real
// colapsa al llegar el streaming y mueve la página (CLS 0.22-0.26 medido en
// prod a 390x844 en primera visita a ?view=tesis/finanzas, 17-nov-2026).
it('compact reserves only the quote block: no metric strip, no chart placeholder', () => {
    render(<CompanyHeaderQuoteSkeleton compact />);
    const skeleton = screen.getByTestId('company-header-quote-skeleton');
    // Bloque de cotización: etiqueta, precio e insignia con las alturas de la
    // variante compacta real (min-h-10/h-10 sm:h-12 y la insignia redondeada).
    expect(skeleton.querySelector('.h-10.w-44')).toHaveClass('sm:h-12');
    expect(skeleton.querySelector('.rounded-full')).toHaveClass('h-7', 'w-40');
    // Nada de tira de métricas (grid de 4 celdas) ni reserva del gráfico.
    expect(skeleton.querySelector('.grid')).toBeNull();
    expect(skeleton.querySelector('.h-\\[400px\\]')).toBeNull();
});

it('default skeleton keeps the full reservation for deferred sections', () => {
    render(<CompanyHeaderQuoteSkeleton />);
    const skeleton = screen.getByTestId('company-header-quote-skeleton');
    const strip = skeleton.querySelector('.grid');
    expect(strip).not.toBeNull();
    expect(strip!.children).toHaveLength(4);
    expect(skeleton.querySelector('.h-\\[400px\\]')).not.toBeNull();
});
