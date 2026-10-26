import type { Metadata } from 'next';
import Link from 'next/link';

import { SUPPORT_EMAIL } from '@/lib/config/brand';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
    title: 'Privacidad',
    description: 'Política de privacidad y tratamiento de datos personales de GerarAI.',
    // Documento en borrador: no se indexa hasta que el responsable complete y
    // valide los campos [PENDIENTE].
    robots: { index: false, follow: false },
    alternates: { canonical: '/privacidad' },
};

const pendingClass =
    'rounded border border-amber-800/60 bg-amber-950/20 px-2 py-0.5 font-mono text-xs text-amber-200';

export default function PrivacyPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">Política de privacidad</h1>
            <p className="mt-2 text-sm text-gray-500">
                Última revisión editorial: <span className={pendingClass}>[PENDIENTE: fecha]</span>.
            </p>

            <div className="mt-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100" role="note">
                <p className="font-semibold">Aviso de borrador: este texto no es una política legal cerrada.</p>
                <p className="mt-1">
                    Los campos marcados como <span className={pendingClass}>[PENDIENTE]</span> debe
                    completarlos el responsable del tratamiento (identidad, base jurídica,
                    regiones, encargados y autoridad de control) antes de abrir el servicio a
                    usuarios externos. Mientras siga siendo borrador, esta página no se indexa
                    y no debe citarse como política definitiva. Este texto no sustituye una
                    revisión jurídica.
                </p>
            </div>

            <article className="prose prose-invert mt-8 max-w-none space-y-6 text-sm leading-7 text-gray-300">
                <section>
                    <h2 className="text-xl font-semibold text-gray-100">1. Responsable del tratamiento</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>Identidad y NIF: <span className={pendingClass}>[PENDIENTE]</span></li>
                        <li>Domicilio: <span className={pendingClass}>[PENDIENTE]</span></li>
                        <li>
                            Contacto de privacidad:{' '}
                            {SUPPORT_EMAIL ? (
                                <a className="text-teal-300 underline" href={`mailto:${SUPPORT_EMAIL}`}>
                                    {SUPPORT_EMAIL}
                                </a>
                            ) : (
                                <span className={pendingClass}>[PENDIENTE: correo de contacto]</span>
                            )}
                        </li>
                        <li>Delegado de Protección de Datos (si aplica): <span className={pendingClass}>[PENDIENTE]</span></li>
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
                        vendemos datos personales ni los usamos para entrenar modelos
                        compartidos.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">3. Finalidades y base jurídica</h2>
                    <p>
                        Tratamos los datos para prestar el servicio que solicitas, proteger la
                        cuenta, cumplir obligaciones legales y atender incidencias. La base
                        jurídica concreta para cada finalidad es{' '}
                        <span className={pendingClass}>[PENDIENTE: ejecución de contrato, consentimiento, interés legítimo u obligación legal]</span>.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">4. Proveedores y subencargados</h2>
                    <p>
                        Según la configuración del despliegue, el servicio puede apoyarse en los
                        siguientes proveedores. El responsable debe confirmar contratos, regiones
                        y garantías de transferencia antes de publicar esta lista:
                    </p>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            <strong>OpenCode Go / OpenCode Zen</strong>: proveedor de modelos de
                            lenguaje cuando el asistente o la generación de tesis estén activados.
                        </li>
                        <li>
                            <strong>Proveedores de datos de mercado</strong>: Finnhub, Financial
                            Modeling Prep, Yahoo Finance, SEC EDGAR, CNMV, FRED, GDELT, CelesTrak y
                            otras fuentes gratuitas configuradas.
                        </li>
                        <li>
                            <strong>Hosting y base de datos</strong>: Vercel (frontend), Render o
                            equivalente (data engine), MongoDB Atlas (autenticación y datos
                            auxiliares), PostgreSQL gestionado.
                        </li>
                        <li>
                            <strong>Almacenamiento y búsqueda</strong>: MinIO o Garage
                            (documentos), Qdrant (índice vectorial) y Redis (cola/caché).
                        </li>
                        <li>
                            <strong>Correo transaccional</strong>: el proveedor SMTP que configure
                            el responsable para avisos y restablecimiento de contraseña.
                        </li>
                    </ul>
                    <p className="mt-2">
                        Regiones y transferencias internacionales: <span className={pendingClass}>[PENDIENTE]</span>.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">5. Conservación</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>
                            Documentos financieros: por defecto 2.555 días (7 años),
                            configurable con <code>FINANCIAL_DOCUMENT_RETENTION_DAYS</code>. Al
                            caducar se borran el original, los fragmentos y los vectores, y se
                            conserva una referencia tombstone sin contenido para que las
                            decisiones históricas sigan siendo auditables.
                        </li>
                        <li>
                            Preguntas crudas de telemetría del chat: por defecto 90 días,
                            configurable con <code>CHAT_TELEMETRY_RETENTION_DAYS</code>.
                        </li>
                        <li>
                            Solicitudes de acceso: por defecto 365 días, expiradas por TTL en
                            MongoDB; configurable con <code>ACCESS_REQUEST_RETENTION_DAYS</code>.
                        </li>
                        <li>
                            Copias de seguridad: <span className={pendingClass}>[PENDIENTE: plazo y procedimiento de expiración]</span>.
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
                        También puedes reclamar ante la autoridad de control competente:{' '}
                        <span className={pendingClass}>[PENDIENTE: AEPD u otra autoridad según jurisdicción]</span>.
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
                            href="https://github.com/nicogarrr/GerarAI"
                            rel="noreferrer"
                            target="_blank"
                        >
                            github.com/nicogarrr/GerarAI
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
                        publicarán en esta página. <span className={pendingClass}>[PENDIENTE: procedimiento de notificación]</span>.
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
