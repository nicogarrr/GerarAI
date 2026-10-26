import { APIError, betterAuth } from "better-auth";
import {mongodbAdapter} from "better-auth/adapters/mongodb";
import {connectToDatabase} from "@/database/mongoose";
import {nextCookies} from "better-auth/next-js";
import {twoFactor} from "better-auth/plugins";
import {env} from "@/lib/env";
import {DatabaseError, toAppError} from "@/lib/types/errors";
import {
    isPasswordResetEmailConfigured,
    sendPasswordResetEmail,
} from "@/lib/auth/email";
import {
    DELETE_REAUTH_HEADER,
    verifyDeleteReauthToken,
} from "@/lib/auth/delete-reauth";
import {deleteAuthAccountResidue} from "@/lib/better-auth/account-residue";


const signUpDisabled =
    process.env.NODE_ENV === 'production' && process.env.ALLOW_PUBLIC_SIGNUP !== 'true';
const requireEmailVerification =
    !signUpDisabled &&
    (process.env.NODE_ENV === 'production' || process.env.REQUIRE_EMAIL_VERIFICATION === 'true');

if (!signUpDisabled && requireEmailVerification) {
    throw new Error(
        'Registro abierto con verificación de email obligatoria, pero auth.ts no tiene sendVerificationEmail ' +
        'configurado: el email de verificación nunca se enviaría y el alta quedaría bloqueada. ' +
        'Implementa el envío de email antes de abrir el registro, o desactiva REQUIRE_EMAIL_VERIFICATION en dev.'
    );
}

const createAuthInstance = (database?: ReturnType<typeof mongodbAdapter>) => betterAuth({
    ...(database ? { database } : {}),
    secret: env.BETTER_AUTH_SECRET,
    baseURL: env.BETTER_AUTH_URL || env.VERCEL_URL || 'http://localhost:3000',
    emailAndPassword: {
        enabled: true,
        // P0: en producción el signup queda cerrado por defecto para evitar
        // creación masiva de cuentas por bots. Para abrirlo de forma
        // controlada usa ALLOW_PUBLIC_SIGNUP=true.
        // En dev/test se mantiene abierto para no friccionar el desarrollo.
        disableSignUp: signUpDisabled,
        // auth.ts no tiene sendVerificationEmail configurado: si el registro
        // está abierto y la verificación es obligatoria, el alta queda
        // bloqueada para siempre (el email de verificación nunca sale). Por
        // eso esa combinación falla al arrancar con un error claro (ver
        // arriba) en lugar de romper el signup en silencio.
        requireEmailVerification: requireEmailVerification,
        minPasswordLength: 8,
        maxPasswordLength: 128,
        autoSignIn: !signUpDisabled && !requireEmailVerification,
        // Un reset invalida las sesiones existentes: si alguien habia robado
        // una cookie, deja de servir en cuanto se cambia la contrasena.
        revokeSessionsOnPasswordReset: true,
        // Sin SMTP no se registra el callback: request-password-reset responde
        // 400 y la UI muestra un estado honesto en lugar de fingir un envio.
        sendResetPassword: isPasswordResetEmailConfigured()
            ? async ({ user, url }) => {
                await sendPasswordResetEmail({
                    to: user.email,
                    name: user.name,
                    url,
                });
            }
            : undefined,
    },
    rateLimit: {
        enabled: env.NODE_ENV === 'production'
            || process.env.APP_ENV === 'production'
            || process.env.AUTH_RATE_LIMIT_ENABLED === 'true',
        window: 60,
        max: 100,
        customRules: {
            '/request-password-reset': { window: 60, max: 3 },
            '/reset-password': { window: 60, max: 5 },
            '/change-password': { window: 10, max: 3 },
            '/verify-password': { window: 60, max: 10 },
            '/delete-user': { window: 60, max: 3 },
        },
    },
    // Perfil inversor persistido en el documento `user` de MongoDB.
    // Mongo es schemaless: additionalFields no requiere migraciones SQL,
    // better-auth los persiste y los devuelve en sesion cuando se piden.
    user: {
        additionalFields: {
            country: { type: 'string', required: false },
            investmentGoals: { type: 'string', required: false },
            riskTolerance: { type: 'string', required: false },
            preferredIndustry: { type: 'string', required: false },
        },
        // Autoservicio real: delete-user borra user, sessions y accounts de
        // Mongo. El endpoint publico NO acepta una sesion fresca como unica
        // prueba: exige un token de reautenticacion firmado que solo emite la
        // accion de servidor despues de verificar la contrasena. Ademas se
        // limpian el secreto TOTP/codigos y las verificaciones pendientes.
        deleteUser: {
            enabled: true,
            beforeDelete: async (deletedUser, request) => {
                const token = request?.headers.get(DELETE_REAUTH_HEADER);
                if (!verifyDeleteReauthToken(
                    token,
                    deletedUser.id,
                    env.BETTER_AUTH_SECRET,
                )) {
                    throw new APIError(401, {
                        message: 'Reautenticación requerida para borrar la cuenta',
                    });
                }
            },
            afterDelete: async (deletedUser) => {
                try {
                    const mongoose = await connectToDatabase();
                    const db = mongoose?.connection?.db;
                    if (!db) {
                        throw new Error('MongoDB is required to clean account residue');
                    }
                    await deleteAuthAccountResidue(db, deletedUser);
                } catch (error: unknown) {
                    console.error(
                        'Better Auth residue cleanup failed:',
                        toAppError(error).code,
                    );
                }
            },
        },
    },
    // nextCookies() SIEMPRE el ultimo: su hook `after` copia a next/headers los
    // Set-Cookie acumulados hasta ese momento. Si va antes de twoFactor(), el
    // navegador recibe el session_token previo al 2FA y nunca la cookie
    // two_factor (ni el borrado de sesion), y el paso TOTP no puede completarse.
    plugins: [
        twoFactor({
            issuer: "CavaAI",
        }),
        nextCookies(),
    ],
});

type AuthInstance = ReturnType<typeof createAuthInstance>;

let authInstance: AuthInstance | null = null;


export const getAuth = async (): Promise<AuthInstance> => {
    if(authInstance) {
        return authInstance;
    }

    try {
        // Validar que BETTER_AUTH_SECRET existe y no es un valor por defecto inseguro
        if (!env.BETTER_AUTH_SECRET) {
            throw new Error('BETTER_AUTH_SECRET is required. Please configure it in your .env file.');
        }

        const mongoose = await connectToDatabase();
        
        // Durante el build, si connectToDatabase retorna null, creamos una instancia sin base de datos
        // Esto permite que el build complete sin necesidad de MongoDB
        if (!mongoose || !mongoose.connection) {
            const isBuildTime = process.env.NEXT_PHASE === 'phase-production-build' || 
                               process.env.NEXT_PHASE === 'phase-development-build';
            
            if (isBuildTime) {
                // Durante el build, creamos una instancia mock sin base de datos
                // Esto permite que Next.js complete el build
                authInstance = createAuthInstance();
                
                return authInstance;
            }
            
            throw new DatabaseError('MongoDB connection is required at runtime');
        }

        const db = mongoose.connection;

        authInstance = createAuthInstance(mongodbAdapter(db));

        return authInstance;
    } catch (error: unknown) {
        const appError = toAppError(error);
        
        // Proporcionar mensaje más útil para errores de MongoDB
        if (appError.message.includes('MongoDB') || appError.message.includes('could not connect')) {
            console.error('\n❌ Error de conexión a MongoDB Atlas');
            console.error('📋 Pasos para solucionar:');
            console.error('1. Ve a: https://cloud.mongodb.com/');
            console.error('2. Selecciona tu proyecto');
            console.error('3. Ve a "Network Access" en el menú lateral');
            console.error('4. Click en "Add IP Address"');
            console.error('5. Para desarrollo: agrega "0.0.0.0/0" (permite todas las IPs)');
            console.error('   Para producción: agrega tu IP específica');
            console.error('6. Espera 1-2 minutos y vuelve a intentar\n');
            
            throw new DatabaseError('MongoDB connection is required at runtime', appError);
        }
        
        throw appError;
    }
}