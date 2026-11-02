import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';

const add = vi.hoisted(() => vi.fn());
vi.mock('@/lib/actions/plan.actions', () => ({ addPlanContribution: add }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh() {}, push() {} }) }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import PlanContributionDialog from '@/components/plan/PlanContributionDialog';

const ACTION_MESSAGE = 'No se pudo registrar la aportación. Revisa la fecha, el importe y la divisa.';

async function submitFailing(locale: 'es' | 'en', trigger: string, save: string) {
    add.mockResolvedValue({ ok: false, message: ACTION_MESSAGE });
    render(<LocaleProvider locale={locale}><PlanContributionDialog defaultAmount={300} defaultCurrency="EUR" /></LocaleProvider>);
    fireEvent.click(screen.getByRole('button', { name: trigger }));
    fireEvent.click(await screen.findByRole('button', { name: save }));
    await waitFor(() => expect(add).toHaveBeenCalled());
}

it('in English, a contribution the server rejects shows the error in English', async () => {
    await submitFailing('en', 'Record contribution', 'Save contribution');
    expect(await screen.findByText('The contribution could not be saved. Check the date, amount and currency.')).toBeInTheDocument();
    expect(screen.queryByText(ACTION_MESSAGE)).not.toBeInTheDocument();
});

it('in Spanish the message stays the same', async () => {
    await submitFailing('es', 'Registrar aportación', 'Guardar aportación');
    expect(await screen.findByText(ACTION_MESSAGE)).toBeInTheDocument();
});
