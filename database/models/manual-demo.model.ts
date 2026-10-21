import { Schema, model, models, type Document, type Model } from 'mongoose';

/**
 * Cuenta demo MANUAL de paper trading (tipo cuenta paper de IBKR).
 * Separada del sistema de propuestas/calibración LLM (proPicks en
 * Postgres/data-engine): colecciones propias con prefijo manualdemo*.
 *
 * Dinero ficticio: 100.000 EUR al crear la cuenta y 0 USD. Las ventas en
 * USD abonan saldo USD; nunca se mezcla con el saldo EUR. La conversión
 * EUR<->USD es una entrada del libro (FxConversion manual simulada).
 */
export interface ManualDemoAccountDoc extends Document {
    userId: string;
    cashEUR: number;
    cashUSD: number;
    /**
     * Versión para escritura condicional (optimistic concurrency): las
     * acciones actualizan cuenta+libro en una transacción con
     * { userId, version } como filtro, evitando write-skew entre dos
     * órdenes concurrentes de la misma cuenta.
     */
    version: number;
    createdAt: Date;
    updatedAt: Date;
}

const ManualDemoAccountSchema = new Schema<ManualDemoAccountDoc>(
    {
        userId: { type: String, required: true },
        cashEUR: { type: Number, required: true, default: 100_000 },
        cashUSD: { type: Number, required: true, default: 0 },
        version: { type: Number, required: true, default: 0 },
    },
    { timestamps: true }
);

ManualDemoAccountSchema.index({ userId: 1 }, { unique: true });

export const MANUAL_DEMO_STARTING_CASH_EUR = 100_000;

export const ManualDemoAccount: Model<ManualDemoAccountDoc> =
    (models?.ManualDemoAccount as Model<ManualDemoAccountDoc>) ||
    model<ManualDemoAccountDoc>('ManualDemoAccount', ManualDemoAccountSchema);

/**
 * Libro mayor de la demo manual. Cada documento es UNA orden: ejecutada
 * (fill) o rechazada. Append-only: no se borran operaciones, como el
 * extracto de un broker. Las posiciones se derivan por contabilidad FIFO
 * en lib/paper-trading/accounting.ts ordenando por executedAt ASC.
 *
 * Modo único de fill: 'manual-simulado' (precio introducido por el
 * usuario, etiquetado en UI). No es una ejecución de mercado ni un motor
 * de órdenes límite: no hay estados pending/working que "se ejecuten".
 */
export interface ManualDemoTradeDoc extends Document {
    userId: string;
    /** Idempotencia: el cliente genera uno por intento de orden. */
    clientOrderId: string;
    kind: 'accion' | 'opcion' | 'fx';
    symbol: string;
    name: string;
    /** Solo opciones: identidad completa del contrato. */
    contract: {
        underlying: string;
        callPut: 'call' | 'put';
        strike: number;
        expiry: string;
        multiplier: number;
        deliverable: 'acciones';
        adjusted: boolean;
    } | null;
    side: 'buy' | 'sell';
    openClose: 'open' | 'close';
    /** Solo fx: divisa origen (el importe va en quantity/price como from/rate). */
    fxFrom: 'EUR' | 'USD' | null;
    fxTo: 'EUR' | 'USD' | null;
    quantity: number;
    status: 'filled' | 'rejected';
    /** Precio de ejecución por acción/prima; null si se rechazó. */
    fillPrice: number | null;
    currency: 'EUR' | 'USD';
    /** Comisión en la divisa del fill. Fase 1: 0 (simplificación documentada). */
    fee: number;
    fillSource: 'manual-simulado';
    /** Cuándo se ejecutó de verdad; el FIFO ordena por esto. */
    executedAt: Date | null;
    rejectReason: string | null;
    createdAt: Date;
    updatedAt: Date;
}

const ManualDemoTradeSchema = new Schema<ManualDemoTradeDoc>(
    {
        userId: { type: String, required: true },
        clientOrderId: { type: String, required: true },
        kind: { type: String, enum: ['accion', 'opcion', 'fx'], required: true },
        symbol: { type: String, required: true, uppercase: true, trim: true },
        name: { type: String, required: true, trim: true },
        contract: { type: Schema.Types.Mixed, default: null },
        side: { type: String, enum: ['buy', 'sell'], required: true },
        openClose: { type: String, enum: ['open', 'close'], required: true },
        fxFrom: { type: String, enum: ['EUR', 'USD', null], default: null },
        fxTo: { type: String, enum: ['EUR', 'USD', null], default: null },
        // @ts-expect-error -- validador condicional por kind; el tipo de
        // Mongoose no admite `this` en validator de path.
        quantity: {
            type: Number,
            required: true,
            min: [0.00000001, 'cantidad positiva'],
            validate: {
                // Acciones y contratos: enteros. FX: importe con decimales
                // permitido (convertir 50,50 EUR no puede exigir entero).
                validator(this: { kind?: string }, v: number) {
                    return this.kind === 'fx' ? v > 0 : Number.isInteger(v) && v >= 1;
                },
                message: 'acciones/contratos enteros; fx admite importe con decimales',
            },
        },
        status: { type: String, enum: ['filled', 'rejected'], required: true },
        fillPrice: { type: Number, default: null },
        currency: { type: String, enum: ['EUR', 'USD'], required: true },
        fee: { type: Number, required: true, default: 0, min: 0 },
        fillSource: { type: String, enum: ['manual-simulado'], required: true },
        executedAt: { type: Date, default: null },
        rejectReason: { type: String, default: null },
    },
    { timestamps: true }
);

// Idempotencia: un clientOrderId por cuenta; reintentos no duplican orden.
ManualDemoTradeSchema.index({ userId: 1, clientOrderId: 1 }, { unique: true });
// Lectura del libro en orden de ejecución (FIFO).
ManualDemoTradeSchema.index({ userId: 1, executedAt: 1 });
ManualDemoTradeSchema.index({ userId: 1, createdAt: -1 });

// Validaciones cruzadas (P1 del auditor): la integridad NO depende solo
// de las actions. Un fill grabado lleva precio>0 y fecha; un rechazo nunca
// lleva precio; fx exige origen/destino distintos; opción exige contrato
// completo y acción lo prohíbe.
// Mongoose 9: middleware de documento async (sin callback next).
ManualDemoTradeSchema.pre('validate', async function validateManualDemoCross(this: ManualDemoTradeDoc) {
    const bad = (msg: string): never => { throw new Error(`manual-demo: ${msg}`); };
    if (this.kind === 'fx') {
        if (!this.fxFrom || !this.fxTo) bad('fx requiere fxFrom y fxTo');
        if (this.fxFrom === this.fxTo) bad('fx con origen === destino crearía dinero');
        if (!(this.fillPrice == null || this.fillPrice > 0)) bad('fx: tipo de cambio (fillPrice) debe ser > 0');
    } else if (this.status === 'filled' && !this.currency) {
        bad('fill de acción/opción requiere divisa (currency)');
    }
    if (this.kind === 'opcion') {
        const c = this.contract as { underlying?: string; expiry?: string; strike?: number } | null;
        if (!c || !c.underlying || !c.expiry || !(typeof c.strike === 'number' && c.strike > 0)) {
            bad('opción requiere contrato completo (underlying, expiry, strike>0)');
        }
    } else if (this.contract != null) {
        bad('acción no lleva contrato de opción');
    }
    if (this.status === 'filled') {
        if (!(typeof this.fillPrice === 'number' && this.fillPrice > 0)) bad('filled requiere fillPrice > 0');
        if (!(this.executedAt instanceof Date) || Number.isNaN(this.executedAt.getTime())) bad('filled requiere executedAt');
    } else if (this.fillPrice != null) {
        bad('rejected no puede llevar fillPrice');
    }
});

export const ManualDemoTrade: Model<ManualDemoTradeDoc> =
    (models?.ManualDemoTrade as Model<ManualDemoTradeDoc>) ||
    model<ManualDemoTradeDoc>('ManualDemoTrade', ManualDemoTradeSchema);
