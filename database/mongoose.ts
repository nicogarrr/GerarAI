import mongoose from "mongoose";

const MONGODB_URI = process.env.MONGODB_URI;

declare global {
    var mongooseCache: {
        conn: typeof mongoose | null;
        promise: Promise<typeof mongoose> | null;
    }
}

let cached = global.mongooseCache;

if (!cached){
    cached = global.mongooseCache = { conn: null, promise: null };
}

export const connectToDatabase = async () => {
    // Durante el build de Next.js, no intentamos conectarnos a MongoDB
    // NEXT_PHASE solo se establece durante el build, no en runtime
    const isBuildTime = process.env.NEXT_PHASE === 'phase-production-build' || 
                       process.env.NEXT_PHASE === 'phase-development-build';
    
    if(!MONGODB_URI){
        if (isBuildTime) {
            // Durante el build, retornamos null en lugar de lanzar error
            // Esto permite que Next.js complete el build sin necesidad de MongoDB
            return null;
        }
        // En runtime, si no hay MONGODB_URI, lanzamos error
        throw new Error("MongoDB URI is missing. Por favor, configura MONGODB_URI en tu archivo .env");
    }

    if(cached.conn) return cached.conn;

    if(!cached.promise) {
        cached.promise = mongoose.connect(MONGODB_URI, {
            bufferCommands: false,
            serverSelectionTimeoutMS: 30000, // Timeout de 30 segundos para dar tiempo a que se propaguen los cambios
            connectTimeoutMS: 30000,
        });
    }

    try{
        cached.conn = await cached.promise;
    }
    catch(err: unknown){
        cached.promise = null;
        
        // Durante el build, no lanzamos error si no se puede conectar
        const isBuildTime = process.env.NEXT_PHASE === 'phase-production-build' || 
                           process.env.NEXT_PHASE === 'phase-development-build';
        
        if (isBuildTime) {
            return null;
        }
        
        // Mensaje de error más descriptivo
        const mongoError = err as { name?: string; message?: string };
        if(mongoError.name === 'MongooseServerSelectionError' || mongoError.message?.includes('could not connect')) {
            throw new Error(
                `No se pudo conectar a MongoDB Atlas. ` +
                `Razones comunes: ` +
                `1) Tu IP no está en la whitelist de MongoDB Atlas - ` +
                `ve a Network Access y agrega tu IP o permite 0.0.0.0/0 para desarrollo. ` +
                `2) La URI de conexión es incorrecta. ` +
                `Error original: ${mongoError.message}`
            );
        }
        
        throw err;
    }

    console.log(`MongoDB Connected successfully in ${process.env.NODE_ENV}`);
    return cached.conn;
}