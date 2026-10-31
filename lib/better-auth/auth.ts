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
import {buildAuthRateLimit} from "@/lib/better-auth/rate-limit";
import {createAuthMiddleware} from "better-auth/api";
import {
    isEmailAllowedToSignUp,
    resolveSignupPolicy,
    SIGNUP_NOT_INVITED_CODE,
    SIGNUP_NOT_INVITED_MESSAGE,
} from "@/lib/auth/signup-policy";
import {
    ACCOUNT_PENDING_CODE,
    ACCOUNT_PENDING_MESSAGE,
    ACCOUNT_REJECTED_CODE,
    ACCOUNT_REJECTED_MESSAGE,
    approvalTokenTtlMs,
    normalizeAccountStatus,
    signupAutoApprove,
} from "@/lib/auth/account-approval";
import { AccountApproval } from "@/database/models/account-approval.model";
import { notifyPendingAccount } from "@/lib/auth/approval-notify";


// Politica de alta compartida con las paginas de acceso (ver
// `lib/auth/signup-policy.ts`): alta cerrada en produccion salvo
// ALLOW_PUBLIC_SIGNUP=true, o abierta solo a los emails de SIGNUP_ALLOWLIST.
// No hay envio de verificacion de email, asi que no se exige (antes, abrir el
// registro en produccion hacia que la app fallara al arrancar).
const signupPolicy = resolveSignupPolicy(process.env);
for (const warning of signupPolicy.warnings) {
    console.warn(`[auth] ${warning}`);
}

// Alta abierta con aprobación (ver lib/auth/account-approval.ts): las cuentas
// nuevas nacen `pending` salvo SIGNUP_AUTO_APPROVE=true (solo e2e/desarrollo;
// playwright.config.ts lo fija en el servidor de user-flows).
const autoApprove = signupAutoApprove(process.env);
if (!autoApprove && (process.env.SIGNUP_AUTO_APPROVE === 'true' || process.env.SIGNUP_AUTO_APPROVE === '1')) {
    console.warn('[auth] SIGNUP_AUTO_APPROVE ignorado: en producción las cuentas nuevas siempre nacen pendientes de aprobación.');
}

const createAuthInstance = (database?: ReturnType<typeof mongodbAdapter>) => betterAuth({
    ...(database ? { database } : {}),
    secret: env.BETTER_AUTH_SECRET,
    baseURL: env.BETTER_AUTH_URL || env.VERCEL_URL || 'http://localhost:3000',
    emailAndPassword: {
        enabled: true,
        // P0: en producción el signup queda cerrado por defecto para evitar
        // creación masiva de cuentas por bots. Se abre a todos con
        // ALLOW_PUBLIC_SIGNUP=true o solo a los emails de SIGNUP_ALLOWLIST
        // (filtrados en `hooks.before`). En dev/test sigue abierto.
        disableSignUp: !signupPolicy.signUpEnabled,
        // Sin envío de verificación configurado: exigirla dejaría el alta
        // bloqueada para siempre (ver `lib/auth/signup-policy.ts`).
        requireEmailVerification: signupPolicy.requireEmailVerification,
        minPasswordLength: 8,
        maxPasswordLength: 128,
        // Con aprobación pendiente el alta NO crea sesión: una cuenta pending
        // nunca obtiene cookie (contrato con front: /cuenta-pendiente).
        autoSignIn: autoApprove && !signupPolicy.requireEmailVerification,
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
    // Con el registro cerrado y lista de invitados, el servidor solo acepta el
    // alta de esos emails: la página puede enseñar el formulario, pero quien
    // decide es este filtro.
    hooks: {
        before: createAuthMiddleware(async (ctx) => {
            if (ctx.path === '/sign-up/email') {
                const email: unknown = (ctx.body as { email?: unknown } | undefined)?.email;
                if (!isEmailAllowedToSignUp(email, signupPolicy)) {
                    throw new APIError(403, {
                        message: SIGNUP_NOT_INVITED_MESSAGE,
                        code: SIGNUP_NOT_INVITED_CODE,
                    });
                }
                return;
            }
            // Cuenta pendiente o rechazada: 403 con código estable, nunca
            // "credenciales inválidas" (contrato con front). Se consulta el
            // estado ANTES de verificar la contraseña: revela existencia de
            // cuentas pendientes, tradeoff aceptado del contrato y cubierto
            // por el rate limit compartido de /api/auth.
            if (ctx.path === '/sign-in/email') {
                const email: unknown = (ctx.body as { email?: unknown } | undefined)?.email;
                const normalized = typeof email === 'string' ? email.trim().toLowerCase() : '';
                if (!normalized) return;
                const mongoose = await connectToDatabase();
                const db = mongoose?.connection?.db;
                if (!db) return;
                const existing = await db.collection('user').findOne(
                    { email: normalized },
                    { projection: { accountStatus: 1 } },
                );
                const status = normalizeAccountStatus(existing?.accountStatus);
                if (status === 'pending') {
                    throw new APIError(403, { message: ACCOUNT_PENDING_MESSAGE, code: ACCOUNT_PENDING_CODE });
                }
                if (status === 'rejected') {
                    throw new APIError(403, { message: ACCOUNT_REJECTED_MESSAGE, code: ACCOUNT_REJECTED_CODE });
                }
            }
        }),
    },
    // Tras crear la cuenta: registro de aprobación + correo a Nico con los
    // enlaces firmados de un solo uso. Un fallo aquí NUNCA rompe el alta ni
    // aprueba la cuenta: fail-closed, el respaldo es /api/admin/approvals.
    databaseHooks: {
        user: {
            create: {
                after: async (createdUser: { id: string; email?: string | null; name?: string | null }) => {
                    if (autoApprove) return;
                    try {
                        const email = (createdUser.email ?? '').trim().toLowerCase();
                        // getAuth ya exige BETTER_AUTH_SECRET al arrancar; si el
                        // tipo dice opcional, aquí se confirma antes de firmar.
                        const secret = env.BETTER_AUTH_SECRET;
                        if (!createdUser.id || !email || !secret) return;
                        const approval = await AccountApproval.create({
                            userId: createdUser.id,
                            email,
                            name: createdUser.name ?? '',
                            expiresAt: new Date(Date.now() + approvalTokenTtlMs(process.env)),
                        });
                        const sent = await notifyPendingAccount({
                            approvalId: String(approval._id),
                            email,
                            name: createdUser.name,
                            secret,
                        });
                        if (sent) {
                            await AccountApproval.updateOne(
                                { _id: approval._id },
                                { $set: { notifiedAt: new Date() } },
                            );
                        } else {
                            console.warn(`[auth] cuenta pendiente ${createdUser.id}: aviso a Nico NO enviado (SMTP sin configurar o caído); respaldo: /api/admin/approvals`);
                        }
                    } catch (error: unknown) {
                        console.error('[auth] alta con aprobación: registro/aviso falló (la cuenta sigue pending):', toAppError(error).code);
                    }
                },
            },
        },
    },
    // Contadores compartidos entre instancias (ver lib/better-auth/rate-limit.ts).
    rateLimit: buildAuthRateLimit({
        hasDatabase: Boolean(database),
        env: {
            NODE_ENV: env.NODE_ENV,
            APP_ENV: process.env.APP_ENV,
            AUTH_RATE_LIMIT_ENABLED: process.env.AUTH_RATE_LIMIT_ENABLED,
        },
    }),
    // Perfil inversor persistido en el documento `user` de MongoDB.
    // Mongo es schemaless: additionalFields no requiere migraciones SQL,
    // better-auth los persiste y los devuelve en sesion cuando se piden.
    user: {
        additionalFields: {
            // Alta abierta con aprobación: input:false + defaultValue hacen que
            // el alta fuerce este valor y el cliente no pueda fijarlo
            // (verificado en la fuente de better-auth 1.7.7, db/schema.mjs).
            accountStatus: {
                type: 'string',
                required: false,
                input: false,
                defaultValue: autoApprove ? 'approved' : 'pending',
            },
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
            issuer: "GerarAI",
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

        // mongodbAdapter espera el Db NATIVO del driver, no la Connection de
        // mongoose (antes pasaba la Connection porque connectToDatabase
        // devolvía any; funcionaba por duck-typing de .collection()).
        const db = mongoose.connection.db;
        if (!db) {
            throw new DatabaseError('MongoDB native database handle is not available');
        }

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