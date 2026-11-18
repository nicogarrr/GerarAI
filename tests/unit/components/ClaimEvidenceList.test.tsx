import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ClaimEvidenceList } from '@/components/research/ClaimEvidenceList';
import type { ResearchClaimEvidence } from '@/lib/actions/research.actions';
import { createTranslator } from '@/lib/i18n/translate';

const evidence = (over: Record<string, unknown> = {}): ResearchClaimEvidence => ({
  id: 7,
  claim_id: 3,
  document_id: 42,
  document_chunk_id: 9,
  evidence_type: 'supports',
  summary: 'Cifras del informe anual',
  source_url: 'https://example.com/informe-anual.pdf',
  source_tier: 'tier_1_regulatory',
  confidence: '0.8000',
  created_at: '2026-11-18T10:00:00Z',
  ...over,
} as ResearchClaimEvidence);

describe('ClaimEvidenceList: cadena de evidencia en la ficha', () => {
  it('con evidencia muestra el tier, la confianza y el enlace http seguro', () => {
    const url = 'https://example.com/informe-anual.pdf';
    render(<ClaimEvidenceList evidence={[evidence()]} locale="es" t={createTranslator('es')} />);

    expect(screen.getByText('1 pruebas')).toBeInTheDocument();
    expect(screen.getByText('Regulatoria · T1')).toBeInTheDocument();
    expect(screen.getByText('Confianza: 0.8000')).toBeInTheDocument();

    const link = screen.getByRole('link', { name: url });
    expect(link).toHaveAttribute('href', url);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('una URL no http no se enlaza: cae al documento_id persistido', () => {
    render(
      <ClaimEvidenceList
        evidence={[evidence({ source_url: 'javascript:alert(1)' })]}
        locale="es"
        t={createTranslator('es')}
      />,
    );

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('#42')).toBeInTheDocument();
  });

  it('sin URL válida ni documento no inventa destino', () => {
    render(
      <ClaimEvidenceList
        evidence={[evidence({ source_url: 'no-es-una-url', document_id: null })]}
        locale="es"
        t={createTranslator('es')}
      />,
    );

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('SIN_DATOS')).toBeInTheDocument();
  });

  it('sin evidencia no pinta nada', () => {
    const { container } = render(<ClaimEvidenceList evidence={[]} locale="es" t={createTranslator('es')} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('limita la lista como el detalle de auditoría y avisa del resto', () => {
    const items = Array.from({ length: 7 }, (_, index) => evidence({ id: index + 1 }));
    render(<ClaimEvidenceList evidence={items} locale="es" t={createTranslator('es')} />);

    expect(screen.getAllByRole('listitem')).toHaveLength(5);
    expect(screen.getByText('y 2 más')).toBeInTheDocument();
  });

  it('respeta el locale para la etiqueta del tier', () => {
    render(<ClaimEvidenceList evidence={[evidence()]} locale="en" t={createTranslator('en')} />);
    expect(screen.getByText('Regulatory · T1')).toBeInTheDocument();
  });
});
