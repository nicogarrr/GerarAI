import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { fairValueWarnings } from '@/lib/research/fair-value-warnings';
import { mapFairValues } from '@/lib/portfolio/holding-signals';

import FairValueWarnings from '@/components/research/FairValueWarnings';

const warning = 'P/B justificado 4,2x acotado a 3x (techo del modelo).';

describe('fair-value warning boundary', () => {
  it.each([undefined, null, '', 'warning', {}, 42])('rejects non-list input: %s', (raw) => {
    expect(fairValueWarnings(raw)).toEqual([]);
  });
  it('keeps every valid warning verbatim and in order, without duplicates', () => {
    const items = [warning, 'NAV llevado a 0.', '  Texto con espacios  ', ...Array.from({ length: 6 }, (_, n) => `Warning ${n}`)];
    expect(fairValueWarnings([null, ...items, '', '  ', 1, {}, warning])).toEqual(items);
  });
  it('does not mutate the source', () => {
    const source = Object.freeze([warning, warning]);
    expect(fairValueWarnings(source)).toEqual([warning]);
    expect(source).toHaveLength(2);
  });
  it('preserves warnings through the holdings mapper, without changing value or source', () => {
    const raw = { value: 20, source: 'motor', label: 'Model', publishable: true, warnings: [warning, null, warning] };
    const mapped = mapFairValues({ items: { SAN: raw } }).SAN;
    expect(mapped).toMatchObject({ value: 20, source: 'motor', warnings: [warning] });
  });
});

describe('FairValueWarnings', () => {
  it.each([undefined, null, [], ['', null, {}]])('renders nothing without valid warnings: %s', (warnings) => {
    const { container } = render(<FairValueWarnings label="Model warnings" warnings={warnings} />);
    expect(container).toBeEmptyDOMElement();
  });
  it('shows every warning in a quiet wrapping list, not hidden behind a hover or live alert', () => {
    render(<FairValueWarnings label="Model warnings" warnings={[warning, 'NAV llevado a 0.']} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    const list = screen.getByRole('list', { name: 'Model warnings' });
    expect(list).toHaveClass('text-xs', 'break-words', 'min-w-0');
    expect(list).not.toHaveAttribute('aria-live');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText(warning)).toBeVisible();
  });
  it('escapes HTML from the API and does not make links or execute it', () => {
    const { container } = render(<FairValueWarnings label="Model warnings" warnings={['<img src=x onerror=alert(1)>']} />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeVisible();
  });
});
