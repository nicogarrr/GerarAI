import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ThesisInvalidationRule } from '@/lib/research/thesis-invalidation-rules';
const mocks = vi.hoisted(() => ({ save: vi.fn() }));
vi.mock('@/lib/actions/research.actions', () => ({ saveThesisInvalidationRules: mocks.save }));
import ThesisInvalidationRulesForm from '@/components/research/ThesisInvalidationRulesForm';
const rule: ThesisInvalidationRule = { metric: 'precio', operator: '<', threshold: 100, description: 'Límite local' };
const open = () => fireEvent.click(screen.getByText('Añadir criterio medible'));
const submit = () => fireEvent.submit(screen.getByRole('button', { name: 'Guardar criterio' }).closest('form')!);
beforeEach(() => vi.clearAllMocks());

describe('Thesis invalidation criteria local interaction', () => {
    it('explains the empty state and validates threshold before calling the action', () => {
        render(<ThesisInvalidationRulesForm ticker="TEST" initialRules={[]} />); open();
        expect(screen.getByText(/Ninguno todavía/)).toBeVisible();
        fireEvent.change(screen.getByLabelText('Umbral'), { target: { value: 'NaN' } }); submit();
        expect(screen.getByRole('alert')).toHaveTextContent('El umbral debe ser un número');
        expect(mocks.save).not.toHaveBeenCalled();
    });
    it('persists a comma-decimal rule preserving prior rules and trims its description', async () => {
        mocks.save.mockResolvedValue({ ok: true, count: 2 });
        render(<ThesisInvalidationRulesForm ticker="TEST" initialRules={[rule]} />); open();
        fireEvent.change(screen.getByLabelText('Umbral'), { target: { value: '−10,5' } });
        fireEvent.change(screen.getByLabelText('Operador'), { target: { value: '<=' } });
        fireEvent.change(screen.getByLabelText('Descripción (opcional)'), { target: { value: '  Revisar  ' } }); submit();
        expect(await screen.findByRole('status')).toHaveTextContent('Se vigilan 2 criterios');
        expect(mocks.save).toHaveBeenCalledWith('TEST', [rule, { metric: 'margen_seguridad_pct', operator: '<=', threshold: -10.5, description: 'Revisar' }]);
        expect(screen.getByLabelText('Umbral')).toHaveValue('');
        expect(screen.getByLabelText('Descripción (opcional)')).toHaveValue('');
        expect(screen.getByText('Límite local', { exact: false })).toBeVisible();
    });
    it('requires a custom metric name then saves the named criterion with no optional description', async () => {
        mocks.save.mockResolvedValue({ ok: true, count: 1 });
        render(<ThesisInvalidationRulesForm ticker="TEST" initialRules={[]} />); open();
        fireEvent.change(screen.getByLabelText('Métrica'), { target: { value: 'metrica:' } });
        fireEvent.change(screen.getByLabelText('Umbral'), { target: { value: '0.08' } }); submit();
        expect(screen.getByRole('alert')).toHaveTextContent('Escribe el nombre');
        expect(mocks.save).not.toHaveBeenCalled();
        fireEvent.change(screen.getByLabelText('Nombre'), { target: { value: ' roic ' } }); submit();
        expect(await screen.findByRole('status')).toHaveTextContent('Se vigila 1 criterio');
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(mocks.save).toHaveBeenCalledWith('TEST', [{ metric: 'metrica:roic', operator: '<', threshold: 0.08, description: null }]);
    });
    it('does not remove existing rules on an action error and recovers when retried', async () => {
        mocks.save.mockResolvedValueOnce({ ok: false, error: 'No disponible' }).mockResolvedValueOnce({ ok: true, count: 0 });
        render(<ThesisInvalidationRulesForm ticker="TEST" initialRules={[rule]} />);
        fireEvent.click(screen.getByRole('button', { name: /Quitar criterio/ }));
        expect(await screen.findByRole('alert')).toHaveTextContent('No disponible');
        expect(screen.getByRole('button', { name: /Quitar criterio/ })).toBeEnabled();
        fireEvent.click(screen.getByRole('button', { name: /Quitar criterio/ }));
        expect(await screen.findByRole('status')).toHaveTextContent('Sin criterios medibles: no se vigila nada.');
        expect(screen.queryByRole('button', { name: /Quitar criterio/ })).not.toBeInTheDocument();
        expect(mocks.save).toHaveBeenLastCalledWith('TEST', []);
    });
    it('blocks duplicate submits and removal while save is pending', async () => {
        let finish!: (result: { ok: true; count: number }) => void;
        mocks.save.mockReturnValue(new Promise(resolve => { finish = resolve; }));
        render(<ThesisInvalidationRulesForm ticker="TEST" initialRules={[{ ...rule, description: null }]} />); open();
        fireEvent.change(screen.getByLabelText('Umbral'), { target: { value: '2' } }); submit();
        expect(screen.getByRole('button', { name: 'Guardando…' })).toBeDisabled();
        expect(screen.getByRole('button', { name: /Quitar criterio/ })).toBeDisabled();
        fireEvent.submit(screen.getByRole('button', { name: 'Guardando…' }).closest('form')!);
        expect(mocks.save).toHaveBeenCalledOnce();
        await act(async () => finish({ ok: true, count: 2 }));
        expect(screen.getByRole('button', { name: 'Guardar criterio' })).toBeEnabled();
    });
});
