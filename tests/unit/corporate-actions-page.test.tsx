// La página es un server component traducido con getT(): lib/i18n/server lee
// la cookie de locale vía next/headers; sin cookie el locale es «es».
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * /corporate-actions: un fallo de red NUNCA se pinta como «0 eventos» (el
 * usuario no puede distinguir motor apagado de nada pendiente), la cuenta
 * respeta el filtro ?ticker y el vacío con ticker nombra el ticker.
 */
const getCorporateActions = vi.fn();
const getCorporateActionsSyncStatus = vi.fn();
vi.mock('@/lib/actions/corporate-actions.actions', () => ({
    getCorporateActions: () => getCorporateActions(),
    getCorporateActionsSyncStatus: () => getCorporateActionsSyncStatus(),
}));
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: () => true }));
vi.mock('@/components/system/BackendOffline', () => ({ default: () => <p>backend caído</p> }));

let viewProps: Record<string, unknown> = {};
vi.mock('@/components/corporate-actions/CorporateActionsView', () => ({
    default: (props: Record<string, unknown>) => {
        viewProps = props;
        return <p>vista de acciones</p>;
    },
}));

import CorporateActionsPage from '@/app/(root)/corporate-actions/page';

const params = (ticker?: string) => Promise.resolve(ticker ? { ticker } : {});

beforeEach(() => {
    viewProps = {};
    getCorporateActions.mockReset();
    getCorporateActionsSyncStatus.mockReset();
    // La página llama a .catch() sobre la promesa: siempre debe ser una promesa.
    getCorporateActionsSyncStatus.mockResolvedValue(null);
});

describe('página de acciones corporativas', () => {
    it('backend caído: pantalla de reintento, nunca «0 eventos» con el motor apagado', async () => {
        getCorporateActions.mockRejectedValue(new Error('ECONNREFUSED'));
        render(await CorporateActionsPage({ searchParams: params() }));
        expect(screen.getByText('backend caído')).toBeInTheDocument();
        expect(screen.queryByText(/0 eventos/)).not.toBeInTheDocument();
    });

    it('la cuenta de la cabecera respeta el filtro ?ticker (sin distinguir mayúsculas)', async () => {
        getCorporateActions.mockResolvedValue([{ ticker: 'TSLA' }, { ticker: 'AAPL' }]);
        const { unmount } = render(await CorporateActionsPage({ searchParams: params() }));
        expect(screen.getByText('2 eventos')).toBeInTheDocument();
        unmount();
        render(await CorporateActionsPage({ searchParams: params('tsla') }));
        expect(screen.getByText('1 eventos')).toBeInTheDocument();
        expect(viewProps.ticker).toBe('TSLA');
    });

    it('vacío con ?ticker: el mensaje nombra el ticker y enlaza de vuelta a su ficha', async () => {
        getCorporateActions.mockResolvedValue([{ ticker: 'AAPL' }]);
        render(await CorporateActionsPage({ searchParams: params('TSLA') }));
        expect(viewProps.emptyMessage).toBe('Sin eventos pendientes de TSLA.');
        expect(screen.getByRole('link', { name: 'Volver a TSLA' })).toHaveAttribute('href', '/research/TSLA');
    });

    it('vacío sin ticker: consulta el estado de importaciones para explicar el vacío', async () => {
        getCorporateActions.mockResolvedValue([]);
        getCorporateActionsSyncStatus.mockResolvedValue(null);
        render(await CorporateActionsPage({ searchParams: params() }));
        expect(getCorporateActionsSyncStatus).toHaveBeenCalled();
        expect(typeof viewProps.emptyMessage).toBe('string');
        expect(viewProps.emptyMessage).not.toBe('');
    });

    it('con eventos visibles no consulta el estado de importaciones', async () => {
        getCorporateActions.mockResolvedValue([{ ticker: 'AAPL' }]);
        render(await CorporateActionsPage({ searchParams: params() }));
        expect(getCorporateActionsSyncStatus).not.toHaveBeenCalled();
        expect(viewProps.emptyMessage).toBeUndefined();
    });
});
