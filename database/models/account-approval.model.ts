import { Schema, model, models, type Document, type Model } from 'mongoose';

/**
 * Registro de aprobación de una cuenta nueva (una fila por usuario).
 *
 * El enlace de aprobar/rechazar del correo a Nico firma el `_id` de este
 * documento; la decisión se consume con un findOneAndUpdate sobre
 * `decidedAt: null`, así que el segundo clic (o un enlace reenviado) cae en
 * 410 y nunca reabre una cuenta ya decidida.
 */
export interface AccountApprovalDoc extends Document {
    userId: string;
    email: string;
    name: string;
    /** Caducidad de los enlaces (defensa adicional a la firma con caducidad). */
    expiresAt: Date;
    decidedAt: Date | null;
    decision: 'approved' | 'rejected' | null;
    /** Claim CAS (Mongo standalone, sin transacciones): quien lo gana decide. */
    processingAt: Date | null;
    processingAction: 'approve' | 'reject' | null;
    /** Fence del claim: solo el dueño de ESTE intento puede finalizar. */
    claimId: string | null;
    /** Claim de una sola vez del aviso AL USUARIO al aprobar (null = no avisado). */
    userNotifiedAt: Date | null;
    /** Cuándo se aplicó la decisión al usuario (null = pendiente de aplicar). */
    appliedAt: Date | null;
    /** null si el aviso a Nico no pudo salir (SMTP sin configurar o caído). */
    notifiedAt: Date | null;
    createdAt: Date;
    updatedAt: Date;
}

const AccountApprovalSchema = new Schema<AccountApprovalDoc>(
    {
        userId: { type: String, required: true },
        email: { type: String, required: true, lowercase: true, trim: true },
        name: { type: String, default: '', trim: true },
        expiresAt: { type: Date, required: true },
        decidedAt: { type: Date, default: null },
        decision: { type: String, enum: ['approved', 'rejected', null], default: null },
        processingAt: { type: Date, default: null },
        processingAction: { type: String, enum: ['approve', 'reject', null], default: null },
        claimId: { type: String, default: null },
        appliedAt: { type: Date, default: null },
        // Claim de un solo uso del aviso AL USUARIO: CAS antes de enviar; se
        // libera si el envío falla para que un reintento pueda avisar.
        userNotifiedAt: { type: Date, default: null },
        notifiedAt: { type: Date, default: null },
    },
    { timestamps: true }
);

AccountApprovalSchema.index({ userId: 1 }, { unique: true });
AccountApprovalSchema.index({ decidedAt: 1, createdAt: -1 });

export const AccountApproval: Model<AccountApprovalDoc> =
    (models?.AccountApproval as Model<AccountApprovalDoc>) ||
    model<AccountApprovalDoc>('AccountApproval', AccountApprovalSchema);
