/**
 * Migración del alta abierta con aprobación (2026-10-31): las cuentas
 * existentes no tienen `accountStatus`; el gate las trata como aprobadas
 * (abuelas), y este script les pone el valor explícito para que el dato
 * diga lo mismo que la regla.
 *
 * Idempotente: solo toca documentos sin el campo. Las cuentas ya marcadas
 * pending/approved/rejected no se tocan.
 *
 * Uso: MONGODB_URI=... node scripts/backfill-account-status.mjs
 *      MONGODB_URI=... node scripts/backfill-account-status.mjs --dry-run
 */
import mongoose from 'mongoose';

const uri = process.env.MONGODB_URI;
if (!uri) {
    console.error('Falta MONGODB_URI en el entorno.');
    process.exit(1);
}
const dryRun = process.argv.includes('--dry-run');

await mongoose.connect(uri);
try {
    const users = mongoose.connection.db.collection('user');
    const filter = { accountStatus: { $exists: false } };
    const candidates = await users.countDocuments(filter);
    if (dryRun) {
        console.log(`[dry-run] cuentas sin accountStatus que quedarían aprobadas: ${candidates}`);
    } else {
        const result = await users.updateMany(filter, { $set: { accountStatus: 'approved' } });
        console.log(`cuentas abuelas marcadas approved: ${result.modifiedCount} (coincidían ${result.matchedCount})`);
    }
    const byStatus = await users.aggregate([
        { $group: { _id: '$accountStatus', n: { $sum: 1 } } },
    ]).toArray();
    console.log('reparto final de accountStatus:', JSON.stringify(byStatus));
} finally {
    await mongoose.disconnect();
}
