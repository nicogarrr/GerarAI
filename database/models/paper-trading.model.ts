import { Schema, model, models, type Document, type Model } from 'mongoose';

/**
 * Cuenta demo de paper trading (tipo cuenta paper de IBKR).
 *
 * El dinero es ficticio y fijo al crear la cuenta: 100.000 EUR. Nunca se
 * conecta con un broker real ni con los permisos de trading del usuario.
 */
export interface PaperAccountDoc extends Document {
    userId: string;
    startingCash: number;
    createdAt: Date;
    updatedAt: Date;
}

const PaperAccountSchema = new Schema<PaperAccountDoc>(
    {
        userId: { type: String, required: true },
        startingCash: { type: Number, required: true },
    },
    { timestamps: true }
);

PaperAccountSchema.index({ userId: 1 }, { unique: true });

export const PAPER_STARTING_CASH = 100_000;

export const PaperAccount: Model<PaperAccountDoc> =
    (models?.PaperAccount as Model<PaperAccountDoc>) ||
    model<PaperAccountDoc>('PaperAccount', PaperAccountSchema);

/**
 * Libro mayor de operaciones demo. Cada documento es UNA operacion
 * (fill o rechazo); las posiciones se derivan por contabilidad FIFO en
 * lib/paper-trading/accounting.ts. No se borran operaciones: la historia
 * completa queda, igual que el extracto de un broker.
 */
export interface PaperTradeDoc extends Document {
    userId: string;
    symbol: string;
    name: string;
    side: 'buy' | 'sell';
    orderType: 'market' | 'limit';
    limitPrice: number | null;
    quantity: number;
    status: 'filled' | 'rejected';
    /** Precio de ejecucion; null si la orden se rechazo. */
    fillPrice: number | null;
    /** Marca temporal de la cotizacion que informa el proveedor (segundos epoch). */
    quoteTimestamp: number | null;
    rejectReason: string | null;
    createdAt: Date;
    updatedAt: Date;
}

const PaperTradeSchema = new Schema<PaperTradeDoc>(
    {
        userId: { type: String, required: true },
        symbol: { type: String, required: true, uppercase: true, trim: true },
        name: { type: String, required: true, trim: true },
        side: { type: String, enum: ['buy', 'sell'], required: true },
        orderType: { type: String, enum: ['market', 'limit'], required: true },
        limitPrice: { type: Number, default: null },
        quantity: { type: Number, required: true, min: 1 },
        status: { type: String, enum: ['filled', 'rejected'], required: true },
        fillPrice: { type: Number, default: null },
        quoteTimestamp: { type: Number, default: null },
        rejectReason: { type: String, default: null },
    },
    { timestamps: true }
);

PaperTradeSchema.index({ userId: 1, createdAt: -1 });

export const PaperTrade: Model<PaperTradeDoc> =
    (models?.PaperTrade as Model<PaperTradeDoc>) ||
    model<PaperTradeDoc>('PaperTrade', PaperTradeSchema);
