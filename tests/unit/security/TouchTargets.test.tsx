import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import PrivacySettings from '@/components/security/PrivacySettings';
import ChangePassword from '@/components/security/ChangePassword';
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock('@/lib/actions/privacy.actions', () => ({ deleteAccount: vi.fn(), exportAccountData: vi.fn() }));
vi.mock('@/lib/actions/password.actions', () => ({ changePassword: vi.fn() }));
describe('mobile touch targets', () => {
  it('preserves deletion safeguards and a clickable enlarged label', () => {
    render(<PrivacySettings email="browser@gerarai.test" />);
    const checkbox = screen.getByRole('checkbox');
    expect(checkbox).toHaveClass('size-5');
    expect(checkbox.closest('label')).toHaveClass('min-h-11');
    expect(screen.getByRole('button', { name: 'Borrar cuenta y todos mis datos' })).toBeDisabled();
    fireEvent.click(screen.getByText('Entiendo que esta acción es irreversible y que no se puede deshacer.'));
    expect(checkbox).toBeChecked();
    expect(screen.getByRole('button', { name: 'Borrar cuenta y todos mis datos' })).toBeDisabled();
    expect(screen.getByText('browser@gerarai.test')).toHaveClass('block');
  });
  it('keeps all password inputs at least44px without changing constraints', () => {
    render(<ChangePassword />);
    for (const label of ['Contraseña actual','Contraseña nueva','Repite la contraseña nueva']) {
      expect(screen.getByLabelText(label)).toHaveClass('min-h-11');
      expect(screen.getByLabelText(label)).toBeRequired();
    }
  });
  it('covers legal, consent, settings, fiscal and sorting targets without broad table changes', () => {
    const source = (path: string) => readFileSync(path, 'utf8');
    for (const file of ['app/(auth)/layout.tsx','app/(public)/layout.tsx']) expect(source(file)).toContain('inline-flex min-h-11 items-center');
    for (const file of ['components/forms/SignUpForm.tsx','components/settings/LlmSettingsForm.tsx','components/settings/IBKRConnectionForm.tsx']) expect(source(file)).toContain('size-5 shrink-0');
    expect(source('components/forms/SignUpForm.tsx')).toContain('min-h-11 cursor-pointer');
    expect(source('app/(root)/watchlist/page.tsx')).toContain('flex min-h-11 items-center px-3 py-2 text-xs');
    expect(source('components/taxes/TaxesView.tsx')).toContain('[&_a.font-mono]:min-h-11');
    expect(source('components/taxes/TaxesView.tsx')).toContain('className="h-11 rounded-md');
  });
});
