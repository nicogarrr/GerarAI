import type { Metadata } from 'next';
import Link from 'next/link';

import { SUPPORT_EMAIL } from '@/lib/config/brand';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
    title: 'Términos de uso',
    description: 'Condiciones de uso del servicio GerarAI.',
    // Documento en borrador: no se indexa hasta que el titular complete y
    // valide los campos [PENDIENTE].
    robots: { index: false, follow: false },
    alternates: { canonical: '/terminos' },
};

const pendingClass =
    'rounded border border-amber-800/60 bg-amber-950/20 px-2 py-0.5 font-mono text-xs text-amber-200';

export default function TermsPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">Términos de uso</h1>
            <p className="mt-2 text-sm text-gray-500">
                Última revisión editorial: <span className={pendingClass}>[PENDIENTE: fecha]</span>.
            </p>

            <div className="mt-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100" role="note">
                <p className="font-semibold">Aviso de borrador.</p>
                <p className="mt-1">
                    Los campos <span className={pendingClass}>[PENDIENTE]</span> los debe
                    completar el titular del servicio antes de abrirlo a usuarios externos.
                    Mientras siga siendo borrador, esta página no se indexa y no debe citarse
                    como términos definitivos. Este documento no es asesoramiento jurídico.
                </p>
            </div>

            <article className="mt-8 space-y-6 text-sm leading-7 text-gray-300">
                <section>
                    <h2 className="text-xl font-semibold text-gray-100">1. Titular del servicio</h2>
                    <p>
                        Nombre legal, NIF y domicilio:{' '}
                        <span className={pendingClass}>[PENDIENTE]</span>. Contacto:{' '}
                        {SUPPORT_EMAIL ? (
                            <a className="text-teal-300 underline" href={`mailto:${SUPPORT_EMAIL}`}>
                                {SUPPORT_EMAIL}
                            </a>
                        ) : (
                            <span className={pendingClass}>[PENDIENTE: correo de contacto]</span>
                        )}
                        .
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">2. Qué es GerarAI</h2>
                    <p>
                        GerarAI es una herramienta educativa de investigación y organización de
                        inversiones. Permite guardar una cartera, construir tesis, enlazar
                        evidencia, seguir una watchlist, configurar alertas y consultar un
                        asistente. No es un bróker, no ejecuta órdenes y no custodia dinero ni
                        valores.
                    </p>
                    <p className="font-medium text-amber-200">
                        GerarAI no ofrece asesoramiento financiero, fiscal o jurídico
                        personalizado. Las decisiones de inversión y sus consecuencias son
                        exclusivamente tuyas. Los datos pueden ser incompletos o llegar con
                        retraso; las etiquetas OFICIAL / INFERIDO / SIN_DATOS no convierten una
                        estimación en un hecho.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">3. Cuenta y seguridad</h2>
                    <p>
                        Debes mantener la confidencialidad de tus credenciales y avisarnos de
                        cualquier uso no autorizado. Puedes activar la verificación en dos pasos
                        y cambiar la contraseña desde{' '}
                        <Link className="text-teal-300 underline" href="/security">/security</Link>.
                        Una cuenta es personal; no compartas el acceso.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">4. Uso aceptable</h2>
                    <ul className="mt-2 list-disc space-y-1 pl-5">
                        <li>No intentes acceder a datos de otras cuentas ni eludir el aislamiento del servicio.</li>
                        <li>No subas contenido ilícito, malware ni datos personales de terceros sin base legal.</li>
                        <li>No abuses de límites, automatizaciones o APIs de proveedores externos.</li>
                        <li>No uses el servicio para operar un negocio de asesoramiento financiero regulado sin cumplir tus obligaciones.</li>
                    </ul>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">5. Datos y proveedores externos</h2>
                    <p>
                        El servicio combina datos de proveedores públicos y privados (SEC EDGAR,
                        CNMV, Finnhub, FMP, Yahoo Finance, FRED, GDELT, CelesTrak, SEC, entre
                        otros) y puede enviar extractos mínimos a un proveedor de modelos de
                        lenguaje cuando actives las funciones correspondientes. Consulta la{' '}
                        <Link className="text-teal-300 underline" href="/privacidad">política de privacidad</Link>{' '}
                        para el detalle y los subencargados.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">6. Propiedad intelectual y licencia</h2>
                    <p>
                        El código de GerarAI se distribuye bajo AGPL-3.0 (
                        <a
                            className="text-teal-300 underline"
                            href="https://github.com/nicogarrr/GerarAI"
                            rel="noreferrer"
                            target="_blank"
                        >
                            repositorio público
                        </a>
                        ). Las marcas, textos editoriales y datos de terceros conservan sus
                        licencias y condiciones. Tus datos y tus tesis siguen siendo tuyos; nos
                        autorizas a tratarlos solo para prestarte el servicio.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">7. Disponibilidad y responsabilidad</h2>
                    <p>
                        El servicio se ofrece «tal cual» y «según disponibilidad». Puede haber
                        interrupciones por mantenimiento, límites de proveedores gratuitos o
                        causas de fuerza mayor. En la medida permitida por la ley, el titular no
                        responde de daños indirectos, lucro cesante o decisiones de inversión
                        basadas en la información mostrada. Los límites concretos de
                        responsabilidad son <span className={pendingClass}>[PENDIENTE]</span>.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">8. Baja y borrado</h2>
                    <p>
                        Puedes exportar tus datos y borrar la cuenta desde{' '}
                        <Link className="text-teal-300 underline" href="/security">/security</Link>.
                        El borrado es inmediato e irreversible y elimina también los documentos
                        originales, los vectores y las sesiones. Los plazos de conservación y las
                        excepciones legales se describen en la{' '}
                        <Link className="text-teal-300 underline" href="/privacidad">política de privacidad</Link>.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">9. Ley aplicable y jurisdicción</h2>
                    <p>
                        Ley aplicable y tribunales competentes:{' '}
                        <span className={pendingClass}>[PENDIENTE]</span>. Si eres consumidor,
                        conservas los derechos imperativos de tu lugar de residencia.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">10. Cambios</h2>
                    <p>
                        Podemos actualizar estos términos. Publicaremos la fecha de revisión y,
                        cuando el cambio sea material, avisaremos por el canal que corresponda:{' '}
                        <span className={pendingClass}>[PENDIENTE: procedimiento]</span>.
                    </p>
                </section>
            </article>

            <p className="mt-10 text-sm text-gray-500">
                Consulta también la{' '}
                <Link className="text-teal-300 underline" href="/privacidad">política de privacidad</Link>.
            </p>
        </main>
    );
}
