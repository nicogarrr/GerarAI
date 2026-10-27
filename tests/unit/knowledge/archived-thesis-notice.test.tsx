import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ArchivedThesisNotice } from '@/components/knowledge/ArchivedThesisNotice';

describe('immutable thesis archive context', () => {
  it('warns before the original content without replacing its number', () => {
    render(<><ArchivedThesisNotice documentType="own_thesis" /><article>Original -64,9 %</article></>);
    expect(screen.getByRole('note')).toHaveTextContent('convención no verificada');
    expect(screen.getByRole('note')).toHaveTextContent('no los compares');
    expect(screen.getByRole('article')).toHaveTextContent('Original -64,9 %');
  });
  it('does not characterize books as an old thesis', () => {
    render(<ArchivedThesisNotice documentType="book" />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});
