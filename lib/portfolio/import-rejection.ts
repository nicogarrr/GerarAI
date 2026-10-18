/**
 * Un Server Action que lanza un error en producción llega al cliente como un
 * 500 con el mensaje borrado («No se pudo completar la operación»). El backend
 * rechaza los ficheros de importación con un 4xx y un motivo en español
 * (cabecera ausente, cuenta distinta, IBKR sin configurar...): ese motivo se
 * devuelve como resultado, no como excepción, para que el usuario lo lea.
 */
const REJECTED_STATUS = new Set([400, 409, 413, 422, 503]);

export type ImportRejection = {
    status: 'rejected';
    message: string;
    positions_imported: 0;
    cash_imported: 0;
    trades_imported: 0;
    dividends_imported: 0;
    fees_imported: 0;
    cash_transactions_imported: 0;
    portfolio_snapshot_id: null;
};

export function importRejection(error: unknown): ImportRejection | null {
    if (!(error instanceof Error)) return null;
    const statusCode = (error as { statusCode?: unknown }).statusCode;
    if (typeof statusCode !== 'number' || !REJECTED_STATUS.has(statusCode)) return null;
    const message = error.message.trim();
    if (!message || /^\d{3}\b/.test(message)) return null;
    return {
        status: 'rejected',
        message,
        positions_imported: 0,
        cash_imported: 0,
        trades_imported: 0,
        dividends_imported: 0,
        fees_imported: 0,
        cash_transactions_imported: 0,
        portfolio_snapshot_id: null,
    };
}
