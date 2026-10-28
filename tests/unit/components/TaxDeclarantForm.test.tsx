/**
 * Aviso suave de formato del NIF del declarante (modelo 720): aparece con
 * formato dudoso o control erróneo, NO con uno válido, y NUNCA bloquea el
 * guardado (puede ser un identificador fiscal extranjero).
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import TaxDeclarantForm from '@/components/settings/TaxDeclarantForm';
import { saveTaxDeclarant } from '@/lib/actions/taxes.actions';

vi.mock('@/lib/actions/taxes.actions', () => ({
  saveTaxDeclarant: vi.fn(),
}));
vi.mock('@/lib/toast', () => ({
  showErrorToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const INITIAL = {
  apellidos_nombre: '',
  nif: '',
  numero_declaracion: '',
  telefono: '',
  filed_720_before: null,
  custody: {},
  custody_entities: {},
  first_acquisition_dates: {},
  partidas: [] as string[],
};

const SAVED = {
  ...INITIAL,
  apellidos_nombre: 'GARCIA, NICO',
  nif: 'DE123456789',
};

function nifInput() {
  return screen.getByLabelText('NIF');
}

describe('TaxDeclarantForm: aviso suave de NIF', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(saveTaxDeclarant).mockResolvedValue(SAVED as never);
  });

  it('sin aviso cuando el NIF está vacío', () => {
    render(<TaxDeclarantForm initial={INITIAL as never} />);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('sin aviso con DNI válido', () => {
    render(<TaxDeclarantForm initial={INITIAL as never} />);
    fireEvent.change(nifInput(), { target: { value: '12345678Z' } });
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('avisa con dígito de control erróneo pero el guardado NO se bloquea', async () => {
    render(<TaxDeclarantForm initial={INITIAL as never} />);
    fireEvent.change(nifInput(), { target: { value: '12345678A' } });
    expect(screen.getByRole('status').textContent).toContain('dígito de control');
    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(saveTaxDeclarant).toHaveBeenCalledTimes(1));
  });

  it('avisa con formato no español (extranjero) y el guardado NO se bloquea', async () => {
    render(<TaxDeclarantForm initial={INITIAL as never} />);
    fireEvent.change(nifInput(), { target: { value: 'DE123456789' } });
    expect(screen.getByRole('status').textContent).toContain('extranjero');
    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(saveTaxDeclarant).toHaveBeenCalledTimes(1));
  });
});
