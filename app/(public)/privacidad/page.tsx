import type { Metadata } from 'next';
import Link from 'next/link';

import { SUPPORT_EMAIL } from '@/lib/config/brand';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
    title: 'Privacidad',
    description: 'Política de privacidad y tratamiento de datos personales de GerarAI.',
    // Texto pendiente de validación jurídica por el titular: no se indexa.
    robots: { index: false, follow: false },
    alternates: { canonical: '/privacidad' },
};

export default function PrivacyPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">Política de privacidad</h1>
            <p className="mt-2 text-sm text-gray-500">Última revisión editorial: 27 de octubre de 2026.</p>

            <div className="mt-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100" role="note">
                <p>
                    Este texto es informativo y no constituye asesoramiento jurídico.
                </p>
            </div>

            <article className="prose prose-invert mt-8 max-w-none space-y-6 text-sm leading-7 text-gray-300">
                <section>
                    <h2 className="text-xl font-semibold text-gray-100">1. Responsable del tratamiento</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>Identidad: Nicolás Iglesias García.</li>
                        <li>
                            Contacto de privacidad:{' '}
                            <a className="text-teal-300 underline" href={`mailto:${SUPPORT_EMAIL}`}>
                                {SUPPORT_EMAIL}
                            </a>
                        </li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">2. Qué datos tratamos</h2>
                    <p>
                        Datos de cuenta (email, nombre, país y preferencias de inversión que
                        decidas facilitar), datos de cartera y operaciones, tesis, claims y
                        evidencia, watchlist, reglas y alertas, documentos que subas y su
                        metadata, notas y memoria de investigación, y mensajes que envíes al
                        asistente. También registramos telemetría técnica del chat (ruta,
                        modelo, latencia y, temporalmente, la pregunta) para operar y mejorar el
                        servicio.
                    </p>
                    <p>
                        No pedimos datos de salud, ideología, religión ni datos biométricos. No
                        vendemos datos personales. El tratamiento que hagan los proveedores de IA
                        depende de sus condiciones y de la configuración elegida.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">3. Finalidades y base jurídica</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            Prestar el servicio que solicitas (cuenta, cartera, tesis, watchlist,
                            alertas, documentos y asistente): ejecución del contrato.
                        </li>
                        <li>
                            Proteger la cuenta, prevenir abusos y operar y mejorar el servicio
                            (incluida la telemetría técnica del chat): interés legítimo.
                        </li>
                        <li>Cumplir obligaciones legales: obligación legal.</li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">4. Proveedores y subencargados</h2>
                    <p>El servicio se apoya en los siguientes proveedores:</p>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            <strong>Modelos de lenguaje</strong>: OpenCode (modelos DeepSeek),
                            Groq, Google (Gemini) y OpenRouter, según la configuración de proveedores.
                            Intervienen en las funciones con IA y reciben el contexto enviado por
                            esas funciones, que puede incluir datos de investigación y de cartera.
                        </li>
                        <li>
                            <strong>Proveedores de datos de mercado</strong>: Finnhub, Financial
                            Modeling Prep, Yahoo Finance, SEC EDGAR, CNMV, FRED, GDELT, CelesTrak
                            y otras fuentes gratuitas configuradas. Estas consultas se hacen por
                            ticker y no incluyen tus datos personales.
                        </li>
                        <li>
                            <strong>Hosting y bases de datos</strong>: Vercel (frontend, con las
                            funciones en la región de Fráncfort, fra1), Oracle Cloud (servidor
                            del motor de datos en la región eu-madrid-1, Madrid, España), MongoDB Atlas (cuentas y datos auxiliares) y
                            PostgreSQL en el propio servidor.
                        </li>
                        <li>
                            <strong>Almacenamiento y búsqueda</strong>: MinIO o Garage
                            (documentos), Qdrant (índice vectorial) y Redis (colas y caché),
                            todos en el propio servidor.
                        </li>
                        <li>
                            <strong>Copias de seguridad</strong>: Cloudflare R2, cuando está
                            configurado.
                        </li>
                        <li>
                            <strong>Correo saliente</strong>: SMTP para avisos y
                            restablecimiento de contraseña, mediante el servidor SMTP configurado.
                        </li>
                    </ul>
                    <p className="mt-2">
                        Regiones y transferencias internacionales: el frontend se ejecuta en la
                        región de Fráncfort (fra1) de Vercel. Los proveedores de modelos de
                        lenguaje y el resto de servicios externos pueden tratar datos fuera de
                        la Unión Europea conforme a sus condiciones.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">5. Conservación</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            Documentos financieros: por defecto 2.555 días (7 años),
                            configurable con <code>FINANCIAL_DOCUMENT_RETENTION_DAYS</code>. La purga
                            requiere activar la tarea de conservación y desactivar el modo de prueba sin borrado.
                            Por defecto está apagada y en modo de prueba sin borrado; esos plazos no garantizan un borrado automático.
                            Cuando se ejecuta la purga, se borran el original, los fragmentos y los vectores, y se
                            conserva una referencia tombstone sin contenido para que las
                            decisiones históricas sigan siendo auditables.
                        </li>
                        <li>
                            Preguntas crudas de telemetría del chat: por defecto 90 días,
                            configurable con <code>CHAT_TELEMETRY_RETENTION_DAYS</code>.
                        </li>
                        <li>
                            Solicitudes de acceso: por defecto 365 días, configurable con{' '}
                            <code>ACCESS_REQUEST_RETENTION_DAYS</code>; el borrado automático
                            por TTL en MongoDB solo se activa si el operador lo habilita
                            expresamente.
                        </li>
                        <li>
                            Copias de seguridad: el script local permite configurar cuántas conservar
                            (8 por defecto); no es una garantía de ejecución. Además,
                            cuando está configurada, una copia en Cloudflare R2 cuya caducidad
                            fija la regla de expiración del bucket.
                        </li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">6. Tus derechos</h2>
                    <p>
                        Puedes solicitar acceso, rectificación, supresión, limitación,
                        portabilidad y oposición. Desde{' '}
                        <Link className="text-teal-300 underline" href="/security">/security</Link>{' '}
                        puedes descargar una copia en JSON de tus datos estructurados y
                        metadatos (perfil, cartera, tesis, claims y evidencia, watchlist,
                        alertas, conocimiento, planes y ajustes) y borrar tu cuenta y todos
                        sus datos. La exportación no incluye los archivos originales de los
                        documentos que hayas subido: de cada documento solo viajan sus
                        metadatos y el recuento de fragmentos. El borrado elimina PostgreSQL,
                        documentos originales, vectores y sesiones; es irreversible.
                    </p>
                    <p>
                        También puedes reclamar ante la Agencia Española de Protección de Datos
                        (AEPD,{' '}
                        <a
                            className="text-teal-300 underline"
                            href="https://www.aepd.es"
                            rel="noreferrer"
                            target="_blank"
                        >
                            www.aepd.es
                        </a>
                        ).
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">7. Seguridad y código fuente</h2>
                    <p>
                        Aplicamos aislamiento por cuenta, autenticación firmada entre frontend y
                        data engine, y restricciones de acceso a datos. Ningún sistema es
                        infalible: si detectas un problema de seguridad, usa el canal de
                        contacto indicado arriba.
                    </p>
                    <p>
                        El código de GerarAI se publica bajo la licencia AGPL-3.0. Puedes
                        consultarlo en{' '}
                        <a
                            className="text-teal-300 underline"
                            href="https://github.com/nicogarrr/gerarai"
                            rel="noreferrer"
                            target="_blank"
                        >
                            github.com/nicogarrr/gerarai
                        </a>
                        . El código fuente correspondiente a la versión desplegada debe estar
                        disponible para los usuarios del servicio.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">8. Cambios</h2>
                    <p>
                        Podemos actualizar esta política para reflejar cambios legales o
                        técnicos. La fecha de la última revisión y los cambios relevantes se
                        publicarán en esta página.
                    </p>
                </section>
            </article>

            <p className="mt-10 text-sm text-gray-500">
                Consulta también los{' '}
                <Link className="text-teal-300 underline" href="/terminos">términos de uso</Link>{' '}
                y la{' '}
                <Link className="text-teal-300 underline" href="/metodologia">metodología</Link>.
            </p>
        </main>
    );
}
