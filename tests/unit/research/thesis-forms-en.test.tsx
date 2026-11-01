import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';

const mocks = vi.hoisted(() => ({ save: vi.fn(), submit: vi.fn() }));
vi.mock('@/lib/actions/research.actions', () => ({ saveThesisInvalidationRules: mocks.save, submitThesisHumanInput: mocks.submit }));

import ThesisInvalidationRulesForm from '@/components/research/ThesisInvalidationRulesForm';
import ThesisHumanInputForm from '@/components/research/ThesisHumanInputForm';
import ThesisApproveButton from '@/components/research/ThesisApproveButton';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

describe('thesis forms in English', () => {
  it('invalidation criteria: labels, rule text and save message', async () => {
    mocks.save.mockResolvedValue({ ok: true, count: 2 });
    render(<LocaleProvider locale="en"><ThesisInvalidationRulesForm ticker="TEST" initialRules={[{ metric: 'margen_seguridad_pct', operator: '<', threshold: -10.5 }]} /></LocaleProvider>);
    expect(screen.getByText('Measurable criteria with alerts')).toBeInTheDocument();
    expect(screen.getByText('margin of safety < -10.50%')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Add a measurable criterion'));
    expect(screen.getByRole('option', { name: 'Margin of safety (%)' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Threshold'), { target: { value: '5' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Save criterion' }).closest('form')!);
    expect(await screen.findByRole('status')).toHaveTextContent('Saved. 2 criteria are checked on every alert run.');
  });

  it('human assumption: English labels and English number format', async () => {
    mocks.submit.mockResolvedValue(undefined);
    render(<LocaleProvider locale="en"><ThesisHumanInputForm ticker="TEST" /></LocaleProvider>);
    fireEvent.click(screen.getByText('Add a human assumption'));
    fireEvent.change(screen.getByLabelText(/Driver key/), { target: { value: 'revenue' } });
    fireEvent.change(screen.getByLabelText(/Fiscal year/), { target: { value: '2027' } });
    fireEvent.change(screen.getByLabelText(/Value/), { target: { value: '1,234.56' } });
    fireEvent.change(screen.getByLabelText(/Source or reference/), { target: { value: 'Q4 deck' } });
    fireEvent.change(screen.getByLabelText(/Rationale/), { target: { value: 'Guidance' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save assumption' }));
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledOnce());
    expect((mocks.submit.mock.calls[0][1] as FormData).get('value')).toBe('1234.56');
    expect(await screen.findByRole('status')).toHaveTextContent('Assumption saved.');
  });

  it('approve button: English labels and blocked reason', () => {
    render(<LocaleProvider locale="en"><ThesisApproveButton ticker="TEST" latestStatus="insufficient_data" latestVersion={3} /></LocaleProvider>);
    expect(screen.getByRole('button', { name: 'Approve thesis' })).toBeDisabled();
    expect(screen.getByText('v3 cannot be published: insufficient data.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
  });
});
