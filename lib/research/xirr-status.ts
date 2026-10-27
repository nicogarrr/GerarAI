/** Reasons must describe missing coverage, not invent absent transactions. */
const XIRR_ND_REASONS: Record<string, string> = {
  incomplete_missing_fx: 'faltan tipos de cambio o valores necesarios para incluir todos los flujos y el valor final',
  incomplete_ambiguous_cash: 'hay flujos de caja ambiguos en el registro',
  insufficient_cashflows: 'faltan flujos de caja en el registro de transacciones',
  no_xirr_root: 'no converge con los flujos registrados',
};

export function xirrUnavailableReason(status: unknown): string {
  return XIRR_ND_REASONS[String(status ?? '')] ?? 'sin flujos suficientes en el registro de transacciones';
}
