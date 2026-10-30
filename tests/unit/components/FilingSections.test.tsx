import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { FilingSection, Modelo720Section } from '@/components/taxes/FilingSections';

const noop = () => {};

function filing(overrides: Record<string, unknown> = {}) {
    return {
        available: true,
        casillas: {
            available: true,
            acciones_negociadas: {
                '0328_transmision_global': 12345.67,
                '0331_adquisicion_global': 10000,
                '0339_suma_ganancias': 2345.67,
                '0340_suma_perdidas': 0,
                rows: [],
            },
            dividendos: { '0029_ingresos_integros': 500 },
        },
        double_taxation: { status: 'ok', total_deduction_base: 12, spanish_withholding_base: { amount: 3 } },
        intereses: { received: { amount_base: 7 } },
        ...overrides,
    };
}

function renderFiling(f: Record<string, unknown> | null) {
    return render(<FilingSection filing={f} year={2025} onPreview={noop} onReset={noop} />);
}

describe('FilingSection estados sin datos', () => {
    it('sin informe muestra N/D, nunca casillas', () => {
        renderFiling(null);
        expect(screen.getByText(/N\/D: genera el informe fiscal/)).toBeInTheDocument();
        expect(screen.queryByText(/0328/)).not.toBeInTheDocument();
    });

    it('available=false usa el motivo del backend', () => {
        renderFiling({ available: false, reason: 'La cartera no usa EUR' });
        expect(screen.getByText(/La cartera no usa EUR/)).toBeInTheDocument();
        expect(screen.queryByText(/0328/)).not.toBeInTheDocument();
    });

    it('available=false sin motivo explica que hace falta EUR como divisa base', () => {
        renderFiling({ available: false });
        expect(screen.getByText(/EUR como divisa base/)).toBeInTheDocument();
    });

    it('casillas no verificadas no publican numeros', () => {
        renderFiling({ available: true, casillas: { available: false, unavailable_reason: 'Ejercicio sin mapeo' } });
        expect(screen.getByText(/Ejercicio sin mapeo/)).toBeInTheDocument();
        expect(screen.queryByText(/0339/)).not.toBeInTheDocument();
    });

    it('casillas sin motivo usan texto de reserva', () => {
        renderFiling({ available: true, casillas: { available: false } });
        expect(screen.getByText(/orden ministerial de ese año/)).toBeInTheDocument();
    });

    it('si el motor no confirma el mapeo (casillas.available no true) muestra N/D', () => {
        renderFiling({ available: true, casillas: {} });
        expect(screen.getByText(/N\/D: el motor no ha confirmado/)).toBeInTheDocument();
    });
});

describe('FilingSection con datos', () => {
    it('formatea importes en euros y muestra las casillas', () => {
        renderFiling(filing());
        expect(screen.getByText(/0328 · Transmisión global/)).toBeInTheDocument();
        const row = screen.getByText(/0328 · Transmisión global/).parentElement!;
        expect(row.textContent).toMatch(/12\.?345,67/);
        expect(row.textContent).toContain('€');
    });

    it('intereses sin tipo de cambio: Sin datos, no 0', () => {
        renderFiling(filing({ intereses: { received: { amount_base: null } } }));
        expect(screen.getByText(/Sin datos: hay intereses sin tipo de cambio/)).toBeInTheDocument();
    });

    it('retenciones espanolas incompletas: Sin datos', () => {
        renderFiling(filing({ double_taxation: { status: 'ok', spanish_withholding_base: { amount: null } } }));
        expect(screen.getByText(/retenciones españolas incompletas/)).toBeInTheDocument();
    });

    it('doble imposicion pendiente de TME pide el TME en vez de un importe', () => {
        renderFiling(filing({ double_taxation: { status: 'pendiente_tme', total_deduction_base: 99, spanish_withholding_base: { amount: 1 } } }));
        expect(screen.getByText(/Falta el tipo medio efectivo/)).toBeInTheDocument();
    });

    it('A15: desglose 0588 por país con el límite bruto × TME de Hacienda', () => {
        // 100 bruto EE. UU., 15 retenido, TME 10 %: min(15, 100 × 0,10) = 10.
        renderFiling(filing({ double_taxation: {
            status: 'calculada_con_tme_manual', total_deduction_base: 10, spanish_withholding_base: { amount: 0 },
            countries: [{ country: 'US', gross_base: 100, withheld_base: 15, treaty_rate: 0.15, treaty_cap_base: 15,
                tme_limit_base: 10, limit_applied: 'bruto_x_tme', deduction_base: 10 }],
        } }));
        const item = screen.getByRole('list', { name: 'Deducción 0588 por país' });
        expect(item.textContent).toMatch(/US: bruto 100,00\s€/);
        expect(item.textContent).toMatch(/bruto × TME 10,00\s€/);
        expect(item.textContent).toMatch(/deducción 10,00\s€ \(manda bruto × TME\)/);
        expect(screen.getByText(/TME del ahorro aplicado al dividendo íntegro/)).toBeInTheDocument();
    });

    it('A15: sin TME el desglose no inventa el límite', () => {
        renderFiling(filing({ double_taxation: {
            status: 'pendiente_tme', spanish_withholding_base: { amount: 0 },
            countries: [{ country: 'US', gross_base: 100, withheld_base: 15, treaty_rate: 0.15, treaty_cap_base: 15,
                tme_limit_base: null, limit_applied: null, deduction_base: null }],
        } }));
        const item = screen.getByRole('list', { name: 'Deducción 0588 por país' });
        expect(item.textContent).toMatch(/bruto × TME falta el TME/);
        expect(item.textContent).toMatch(/deducción N\/D/);
    });

    it('interes de margen solo aparece si es positivo y avisa de que no se resta', () => {
        const { unmount } = renderFiling(filing({ intereses: { received: { amount_base: 1 }, margin_interest_paid: { amount_base: 0 } } }));
        expect(screen.queryByText(/Intereses de margen pagados/)).not.toBeInTheDocument();
        unmount();
        renderFiling(filing({ intereses: { received: { amount_base: 1 }, margin_interest_paid: { amount_base: 40 } } }));
        expect(screen.getByText(/no se restan en la declaración/)).toBeInTheDocument();
    });

    it('compensacion de perdidas estimativa se declara como estimativa', () => {
        renderFiling(filing({ loss_compensation: { estimativo: true, remaining_to_carry_base: 250 } }));
        expect(screen.getByText(/Estimativa \(no trasladable a casillas\)/)).toBeInTheDocument();
    });

    it('compensacion aplicada muestra ganancias y rendimientos', () => {
        renderFiling(filing({ loss_compensation: { applied_to_gains_total_base: 100, applied_to_income_total_base: 20 } }));
        expect(screen.getByText(/Aplicada: .* a ganancias y .* a rendimientos/)).toBeInTheDocument();
    });

    it('deduccion parcial avisa N/D y lista revision manual y pagos especiales', () => {
        renderFiling(filing({
            double_taxation: { status: 'ok', partial: true, manual_review: [{ ticker: 'BN', reason: 'sin retencion' }], spanish_withholding_base: { amount: 1 } },
            casillas: { available: true, acciones_negociadas: { rows: [] }, dividendos: { special_payment_tickers: ['XYZ', 'ABC'] } },
        }));
        expect(screen.getByText(/N\/D en la deducción total/)).toBeInTheDocument();
        expect(screen.getByText(/BN: /)).toBeInTheDocument();
        expect(screen.getByText(/Pagos especiales .*XYZ, ABC/)).toBeInTheDocument();
    });

    it('muestra el TME manual aplicado solo si es numero', () => {
        const { unmount } = renderFiling(filing({ tme_percent_manual: 21.5 }));
        expect(screen.getByText('TME manual aplicado (%)')).toBeInTheDocument();
        unmount();
        renderFiling(filing({ tme_percent_manual: '21' }));
        expect(screen.queryByText('TME manual aplicado (%)')).not.toBeInTheDocument();
    });
});

describe('Modelo720Section', () => {
    it('sin umbrales y sin error no pinta nada', () => {
        const { container } = render(<Modelo720Section thresholds={null} file720={null} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('error del motor: dice que no significa que no aplique', () => {
        render(<Modelo720Section thresholds={null} file720={null} unavailable />);
        expect(screen.getByText(/No significa que no te aplique/)).toBeInTheDocument();
    });

    const thresholds = {
        fiscal_year: 2025,
        categories: {
            valores: { status: 'supera', total_eur: 60000, missing_isin: ['AAA'], reasons: ['razon1'] },
            cuentas: { status: 'desconocido', reasons: [] },
            inmuebles: { status: 'no_evaluable' },
        },
        short_positions: [{ ticker: 'SHRT' }],
    };

    it('estados por categoria y avisos', () => {
        render(<Modelo720Section thresholds={thresholds} file720={null} />);
        expect(screen.getByText('Supera el umbral de 50.000 €')).toBeInTheDocument();
        expect(screen.getByText('No concluyente (faltan datos)')).toBeInTheDocument();
        expect(screen.getByText('No evaluable con datos de bróker')).toBeInTheDocument();
        expect(screen.getByText(/Sin ISIN .*AAA/)).toBeInTheDocument();
        expect(screen.getByText(/SHRT: posición corta/)).toBeInTheDocument();
    });

    it('A17: una cuenta con saldo 0 a 31/12 se nombra con el motivo, no se omite', () => {
        render(<Modelo720Section thresholds={{ ...thresholds, zero_balance_accounts: [{
            ticker: 'cash-USD', account: 'Cuenta en USD (cartera «Main»)', currency: 'USD',
            reason: 'Saldo 0 a 31/12 y saldo medio del 4.º trimestre también 0: no suma nada al umbral de cuentas, por eso no se incluye en el total.',
        }] }} file720={null} />);
        expect(screen.getByText(/Cuenta en USD \(cartera «Main»\): Saldo 0 a 31\/12/)).toBeInTheDocument();
        expect(screen.getByText(/no se incluye en el total/)).toBeInTheDocument();
    });

    it('estado desconocido no muestra un importe inventado', () => {
        render(<Modelo720Section thresholds={thresholds} file720={null} />);
        const row = screen.getByText('Cuentas en el extranjero').parentElement!;
        expect(row.textContent).not.toMatch(/0,00/);
    });

    it('fichero sin contenido no ofrece descarga', () => {
        render(<Modelo720Section thresholds={thresholds} file720={{ available: true, detail_records: 3 }} />);
        expect(screen.queryByText('Descargar borrador del 720')).not.toBeInTheDocument();
        expect(screen.getByText(/no su contenido/)).toBeInTheDocument();
    });

    it('recuento ausente no se convierte en cero fiscal', () => {
        render(<Modelo720Section thresholds={thresholds} file720={{ available: true, detail_records: null }} />);
        expect(screen.getByText(/null registros de detalle/)).toBeInTheDocument();
        expect(screen.queryByText(/0 registros de detalle/)).not.toBeInTheDocument();
    });

    it('fichero no disponible muestra motivo', () => {
        render(<Modelo720Section thresholds={thresholds} file720={{ available: false, reason: 'faltan ISIN' }} />);
        expect(screen.getByText(/faltan ISIN/)).toBeInTheDocument();
    });

    it('descarga reconstruye bytes latin-1 (un caracter = un byte)', async () => {
        let blob: Blob | null = null;
        (URL as any).createObjectURL = vi.fn((b: Blob) => { blob = b; return 'blob:x'; });
        (URL as any).revokeObjectURL = vi.fn();
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
        render(<Modelo720Section thresholds={thresholds}
            file720={{ available: true, detail_records: 1, record_length: 500, encoding: 'ISO-8859-1', content: 'Ñá\u00ff', notas: ['n1'], excluded: [{ ticker: 'EX', reason: 'r' }], manual_review: [{ ticker: 'MR', reason: 'r2' }] }} />);
        expect(screen.getByText(/1 registro de detalle de 500 bytes/)).toBeInTheDocument();
        expect(screen.getByText('n1')).toBeInTheDocument();
        expect(screen.getByText(/EX: r/)).toBeInTheDocument();
        expect(screen.getByText(/MR: r2/)).toBeInTheDocument();
        fireEvent.click(screen.getByText('Descargar borrador del 720'));
        expect(click).toHaveBeenCalled();
        const buf = new Uint8Array(await new Promise<ArrayBuffer>((res) => { const r = new FileReader(); r.onload = () => res(r.result as ArrayBuffer); r.readAsArrayBuffer(blob!); }));
        expect(Array.from(buf)).toEqual([0xd1, 0xe1, 0xff]);
    });
});
