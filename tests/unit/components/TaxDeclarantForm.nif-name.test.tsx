/**
 * El aviso suave del NIF no debe pasar al NOMBRE accesible del campo: al
 * renderizarse dentro del <label>, el cómputo de nombre lo absorbía y un
 * lector de pantalla anunciaba toda la advertencia como nombre del input.
 * El aviso corresponde a la descripción (aria-describedby), no al nombre.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import TaxDeclarantForm from '@/components/settings/TaxDeclarantForm';

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

describe('TaxDeclarantForm: nombre accesible del campo NIF', () => {
  it('el aviso suave no se cuela en el nombre accesible (sigue siendo «NIF»)', () => {
    render(<TaxDeclarantForm initial={INITIAL as never} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'NIF' }), { target: { value: '12345678A' } });
    expect(screen.getByRole('status').textContent).toMatch(/dígito de control/);
    const input = screen.getByRole('textbox', { name: 'NIF' });
    expect(input).toHaveAccessibleName('NIF');
    expect(input).toHaveAccessibleDescription(/dígito de control/);
  });
});
