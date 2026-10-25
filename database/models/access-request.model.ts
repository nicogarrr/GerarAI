import { Schema, model, models, type Document, type Model } from 'mongoose';

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

// Retencion: Mongo expira la solicitud completa (email, nombre, nota e IP
// hasheada) pasado el periodo configurado. El indice TTL se nombra aparte
// para no competir con el indice normal de createdAt. Un valor invalido cae
// al default seguro de 365 dias.
const retentionDays = Number(process.env.ACCESS_REQUEST_RETENTION_DAYS ?? 365);
AccessRequestSchema.index(
    { createdAt: 1 },
    {
        name: 'access_request_retention_ttl',
        expireAfterSeconds:
            (Number.isFinite(retentionDays) && retentionDays > 0 ? retentionDays : 365) * 86_400,
    }
);

export const AccessRequest: Model<AccessRequestDoc> =
    (models?.AccessRequest as Model<AccessRequestDoc>) ||
    model<AccessRequestDoc>('AccessRequest', AccessRequestSchema);
