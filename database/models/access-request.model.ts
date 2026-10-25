import { Schema, model, models, type Document, type Model } from 'mongoose';
import { accessRequestTtlSeconds } from '@/lib/access-request-retention';

export interface AccessRequestDoc extends Document {
    email: string;
    name: string;
    note: string;
    status: 'pending' | 'approved' | 'rejected';
    /** Huella de la IP (nunca la IP en claro) para limitar abusos. */
    ipHash: string;
    /** Cuantas veces ha enviado la misma solicitud el mismo email. */
    submissions: number;
    notifiedAt: Date | null;
    createdAt: Date;
    updatedAt: Date;
}

const AccessRequestSchema = new Schema<AccessRequestDoc>(
    {
        email: { type: String, required: true, lowercase: true, trim: true },
        name: { type: String, required: true, trim: true },
        note: { type: String, default: '', trim: true },
        status: { type: String, enum: ['pending', 'approved', 'rejected'], default: 'pending' },
        ipHash: { type: String, required: true },
        submissions: { type: Number, default: 1 },
        notifiedAt: { type: Date, default: null },
    },
    { timestamps: true }
);

// Una solicitud por email: reenviar no crea otra fila.
AccessRequestSchema.index({ email: 1 }, { unique: true });
AccessRequestSchema.index({ ipHash: 1, createdAt: -1 });
AccessRequestSchema.index({ status: 1, createdAt: -1 });

// Retencion por TTL de Mongo: APAGADA por defecto (ver lib/access-request-retention.ts).
// Antes de activarla hay que contar los candidatos y revisar el alcance.
const ttlSeconds = accessRequestTtlSeconds(process.env);
if (ttlSeconds !== null) {
    AccessRequestSchema.index({ createdAt: 1 }, { name: 'access_request_retention_ttl', expireAfterSeconds: ttlSeconds });
}

export const AccessRequest: Model<AccessRequestDoc> =
    (models?.AccessRequest as Model<AccessRequestDoc>) ||
    model<AccessRequestDoc>('AccessRequest', AccessRequestSchema);
