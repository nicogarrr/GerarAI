import { expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import fs from 'node:fs';
import { SotpBreakdownSkeleton } from '@/components/research/SotpBreakdownSkeleton';

it('reserves the card, variants and table rows without announcing fake data', () => {
  const { container } = render(<SotpBreakdownSkeleton />);
  const card = container.querySelector('section');
  expect(card?.getAttribute('aria-hidden')).toBe('true');
  expect(card?.classList.contains('min-w-0')).toBe(true);
  expect(card?.textContent).toBe('');
  expect(card?.querySelectorAll('a,button,input,[tabindex]')).toHaveLength(0);
  expect(card?.querySelectorAll('.motion-safe\\:animate-pulse')).toHaveLength(18);
  expect(card?.querySelectorAll('.border-t')).toHaveLength(1);
});

it('renders deterministically on the server without fetching SOTP', () => {
  const first = renderToStaticMarkup(<SotpBreakdownSkeleton />);
  expect(renderToStaticMarkup(<SotpBreakdownSkeleton />)).toBe(first);
  expect(first).toContain('aria-hidden="true"');
  if (process.env.SOTP_VISUAL_HTML) fs.writeFileSync(process.env.SOTP_VISUAL_HTML, first);
});
