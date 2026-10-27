import type { Metadata } from 'next';
import Link from 'next/link';

import { SUPPORT_EMAIL } from '@/lib/config/brand';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
    title: 'Términos de uso',
    description: 'Condiciones de uso del servicio GerarAI.',
    // Texto pendiente de validación jurídica por el titular: no se indexa.
    robots: { index: false, follow: false },
    alternates: { canonical: '/terminos' },
};

export default function TermsPage() {
    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-3xl px-4 py-12">
            <h1 className="text-3xl font-bold text-gray-100">Términos de uso</h1>
            <p className="mt-2 text-sm text-gray-500">Última revisión editorial: 27 de octubre de 2026.</p>

            <div className="mt-6 rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100" role="note">
                <p>Este documento es informativo y no constituye asesoramiento jurídico.</p>
            </div>

            <article className="mt-8 space-y-6 text-sm leading-7 text-gray-300">
                <section>
                    <h2 className="text-xl font-semibold text-gray-100">1. Titular del servicio</h2>
                    <p>
                        GerarAI es un proyecto personal de Nicolás Iglesias García (España).
                        Contacto:{' '}
                        <a className="text-teal-300 underline" href={`mailto:${SUPPORT_EMAIL}`}>
                            {SUPPORT_EMAIL}
                        </a>
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
                        CNMV, Finnhub, FMP, Yahoo Finance, FRED, GDELT y CelesTrak, entre otros)
                        y puede enviar extractos mínimos a un proveedor de modelos de lenguaje
                        cuando actives las funciones correspondientes. Consulta la{' '}
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
                            href="https://github.com/nicogarrr/gerarai"
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
                        basadas en la información mostrada.
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
                        Estos términos se rigen por la ley española. Si eres consumidor,
                        conservas los derechos imperativos y el fuero de tu lugar de residencia.
                    </p>
                </section>

                <section>
                    <h2 className="text-xl font-semibold text-gray-100">10. Cambios</h2>
                    <p>
                        Podemos actualizar estos términos. Publicaremos la fecha de la última
                        revisión en esta página.
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
