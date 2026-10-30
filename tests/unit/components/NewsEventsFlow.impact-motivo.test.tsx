import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
vi.mock('next/link',()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
import { ImpactBadge } from '@/components/research/NewsEventsFlow';

describe('etiqueta de impacto con motivo en una linea',()=>{
 it('muestra impacto y motivo real del tipo de evento',()=>{
  render(<ImpactBadge direction="negative" eventType="dilution"/>);
  const badge=screen.getByText('Negativo · Dilución');
  expect(badge).toHaveAttribute('title',expect.stringContaining('Lectura automática'));
  expect(badge).toHaveAttribute('aria-label',expect.stringContaining('motivo: Dilución'));
 });
 it('omite el motivo cuando el tipo no explica nada (general/unknown) en vez de rellenar',()=>{
  const {container}=render(<><ImpactBadge direction="neutral" eventType="general_news"/><ImpactBadge direction="positive" eventType="unknown"/></>);
  expect(screen.getByText('Neutro')).toBeInTheDocument();
  expect(screen.getByText('Positivo')).toBeInTheDocument();
  expect(container).not.toHaveTextContent('Noticia general');
  expect(container).not.toHaveTextContent('Desconocido');
 });
 it('sin direction no pinta nada (dato ausente, nunca inventado)',()=>{
  const {container}=render(<ImpactBadge direction={null} eventType="earnings"/>);
  expect(container).toBeEmptyDOMElement();
 });
});
