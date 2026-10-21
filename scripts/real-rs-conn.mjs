// Conector REAL a un MongoDB replica set efímero para la prueba de acciones.
import mongoose from 'mongoose';
let uri = null;
export function __setUri(u) { uri = u; }
export async function connectToDatabase() {
    if (mongoose.connection.readyState !== 1) await mongoose.connect(uri);
    return mongoose;
}
