'use client';

import Link from 'next/link';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SUPPORT_EMAIL } from '@/lib/config/brand';
import { useLocale } from '@/lib/i18n/client';
import { FAQS_EN, FirstStepsEn, GlossaryEn, HELP_EN, LoginNoteEn, MODULES_EN } from '@/components/help/help-copy-en';

const modules = [
  {
    href: '/research',
    title: 'Research',
    text: 'Ficha por ticker: hechos financieros canónicos, métricas trazables, tesis, moat, pares, valoración y chat con fuentes.',
  },
  {
    href: '/research',
    title: 'Modelo a largo plazo',
    text: 'Modelo fundamental con supuestos visibles (crecimiento, margen FCF, WACC), escenarios Bear/Base/Bull con sus spreads, owner earnings, TAM/SAM/SOM y reverse DCF. Pestaña «Modelo» de la ficha.',
  },
  {
    href: '/portfolio',
    title: 'Cartera',
    text: 'Posiciones, transacciones, importación desde IBKR y desglose por sector y divisa.',
  },
  {
    href: '/risk',
    title: 'Exposiciones',
    text: 'Pesos, concentración (top 1 y top 5) y exposición por sector y factor. No calcula VaR, drawdown ni volatilidad: son métricas de estructura de cartera.',
  },
  {
    href: '/screeners',
    title: 'Screener',
    text: 'Universo de grandes capitalizaciones con perfiles y precios reales para partir de candidatos verificables.',
  },
  {
    href: '/propicks',
    title: 'ProPicks',
    text: 'Scores 0-100 con motivos auditables (cada motivo muestra su métrica y su valor) y backtest por estrategia comparado contra el S&P 500.',
  },
  {
    href: '/alerts',
    title: 'Alertas',
    text: 'Señales con umbral de materialidad explícito, enlazadas a la ficha de la compañía.',
  },
  {
    href: '/insider',
    title: 'Insider',
    text: 'Operaciones de personas vinculadas (Form 4 de la SEC) con señales por cluster de compra.',
  },
  {
    href: '/knowledge',
    title: 'Knowledge y búsqueda',
    text: 'Biblioteca de principios de inversión e índice semántico que se reconstruye desde Postgres.',
  },
  {
    href: '/watchlist',
    title: 'Watchlist',
    text: 'Seguimiento de símbolos con enlace directo a su ficha de research.',
  },
  {
    href: '/metodologia',
    title: 'Metodología',
    text: 'Motores de valoración con sus supuestos, fuentes de datos, límites (look-ahead, cobertura parcial) y costes explícitos.',
  },
];

const faqs = [
  {
    question: "¿Cuánto cuesta usar GerarAI?",
    answer: "La app no tiene planes de pago ni cobra por usarla. Funciona con proveedores de datos de capa gratuita (Finnhub, Yahoo Finance, SEC EDGAR), lo que limita la cobertura y la frescura de algunos datos."
  },
  {
    question: "¿Esto es asesoramiento financiero?",
    answer: "No. GerarAI es una herramienta de análisis: los modelos y las tesis dependen de supuestos visibles y pueden fallar. Las decisiones de inversión son tuyas."
  },
  {
    question: "¿Cómo sigo una compañía?",
    answer: "Abre su ficha en Research y pulsa «Seguir», junto al nombre. Los símbolos que sigues se recogen en tu watchlist."
  },
  {
    question: "¿Qué hago si encuentro un error o tengo una sugerencia?",
    answer: "Escribe a la dirección de la pestaña Contacto, con la página y lo que esperabas ver. No se garantiza un plazo de respuesta."
  },
  {
    question: "¿Los datos de mercado son en tiempo real?",
    answer: "No. Los datos de mercado llegan con retraso en la mayoría de mercados: sirven para análisis, no para operar en intradía. En watchlist y research, cada precio indica la fecha de su cierre."
  }
];

export default function HelpTabs() {
  // Inglés con Ajustes → Idioma; el español es el texto de este archivo.
  const en = useLocale() === 'en';
  return (
    <main id="content" tabIndex={-1} className="mx-auto w-full max-w-4xl px-4 py-12">
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold text-gray-100 mb-4">{en ? HELP_EN.title : 'Centro de ayuda'}</h1>
        <p className="text-xl text-gray-200 mb-4">
          {en ? HELP_EN.subtitle : 'Documentación, preguntas frecuentes y soporte'}
        </p>
        <p className="mt-4 text-sm text-gray-400">
          {en ? HELP_EN.methodologyQuestion : '¿Quieres ver cómo analizamos y de dónde salen los datos?'}{' '}
          <Link href="/metodologia" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">
            {en ? HELP_EN.methodologyLink : 'Metodología y fuentes'}
          </Link>
        </p>
        {/* Esta página es pública, pero casi todos los módulos que documenta
            viven dentro de la app. Se avisa aquí para que nadie pulse un enlace
            y se encuentre de golpe con el formulario de acceso. */}
        <p className="mx-auto mt-6 max-w-2xl rounded-lg border border-gray-700/50 bg-gray-800/60 p-4 text-left text-sm text-gray-300">
          {en ? <LoginNoteEn /> : (<>
          Los enlaces a <span className="text-gray-100">research</span>,{' '}
          <span className="text-gray-100">cartera</span>, <span className="text-gray-100">riesgo</span>,{' '}
          <span className="text-gray-100">ProPicks</span>, <span className="text-gray-100">alertas</span>,{' '}
          <span className="text-gray-100">insiders</span>, <span className="text-gray-100">watchlist</span> y{' '}
          <span className="text-gray-100">exportación</span>{' '}
          describen módulos del espacio de trabajo y{' '}
          <strong className="text-gray-100">requieren iniciar sesión</strong>. Esta página de ayuda y la
          metodología se leen sin cuenta.
          </>)}
        </p>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="faq" className="w-full">
        <TabsList
          tabIndex={0}
          aria-label={en ? HELP_EN.tabsAria : 'Secciones de la ayuda'}
          className="mb-8 flex h-auto w-max min-w-full snap-x gap-1 overflow-x-auto border border-gray-700 bg-gray-800 pb-2 text-gray-400 sm:inline-flex sm:h-9 sm:w-auto sm:overflow-visible sm:pb-[3px]"
        >
          <TabsTrigger
            value="faq"
            className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300"
          >
            FAQs
          </TabsTrigger>
          <TabsTrigger
            value="api"
            className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300"
          >
            {en ? HELP_EN.tabDocs : 'Documentación'}
          </TabsTrigger>
          <TabsTrigger
            value="community"
            className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300"
          >
            {en ? HELP_EN.tabContact : 'Contacto'}
          </TabsTrigger>
        </TabsList>

        {/* FAQ Tab */}
        <TabsContent value="faq">
          {/* Help Philosophy */}
          <div className="grid md:grid-cols-3 gap-6 mb-12">
            <div className="bg-gray-800 rounded-lg shadow-sm p-6 border hover:shadow-md transition-shadow">
              <h2 className="text-lg font-semibold text-blue-500 mb-2">{en ? HELP_EN.learnTitle : 'Aprende'}</h2>
              <p className="text-gray-200 text-sm">
                {en ? HELP_EN.learnText : 'La pestaña Documentación explica qué hace cada módulo hoy y cómo usarlo, con enlace a la metodología y las fuentes.'}
              </p>
            </div>

            <div className="bg-gray-800 rounded-lg shadow-sm p-6 border hover:shadow-md transition-shadow">
              <h2 className="text-lg font-semibold text-green-500 mb-2">{en ? HELP_EN.supportTitle : 'Soporte'}</h2>
              <p className="text-gray-200 text-sm">
                {en ? HELP_EN.supportText : 'El soporte es por email y lo atiende quien mantiene el proyecto. No hay un plazo de respuesta garantizado.'}
              </p>
            </div>

            <div className="bg-gray-800 rounded-lg shadow-sm p-6 border hover:shadow-md transition-shadow">
              <h2 className="text-lg font-semibold text-purple-400 mb-2">{en ? HELP_EN.sourcedTitle : 'Datos con fuente'}</h2>
              <p className="text-gray-200 text-sm">
                {en ? HELP_EN.sourcedText : 'Las cifras de research indican su fuente y su fecha. Si no hay dato verificable, la app muestra N/D en vez de inventarlo.'}
              </p>
            </div>
          </div>

          {/* Community FAQs */}
          <section className="mb-12">
            <h2 className="text-3xl font-bold text-gray-100 mb-8 text-center">{en ? HELP_EN.faqTitle : 'Preguntas frecuentes'}</h2>
            <div className="space-y-4">
              {(en ? FAQS_EN : faqs).map((faq) => (
                <div key={faq.question} className="bg-gray-800 rounded-lg shadow-sm p-6 border">
                  <h3 className="text-lg font-semibold text-gray-100 mb-2">{faq.question}</h3>
                  <p className="text-gray-200">{faq.answer}</p>
                </div>
              ))}
            </div>
          </section>
        </TabsContent>

        {/* Documentation Tab */}
        <TabsContent value="api" className="mt-0">
          <div className="space-y-8">
            <div className="mb-8">
              <h2 className="text-3xl font-bold text-gray-100 mb-4">{en ? HELP_EN.docsTitle : 'Documentación'}</h2>
              <p className="text-xl text-gray-200 mb-4">
                {en ? HELP_EN.docsSubtitle : 'Guía práctica por módulo: lo que la app hace hoy y cómo usarla.'}
              </p>
            </div>

            {/* Primeros pasos */}
            <section className="bg-gray-800 rounded-lg shadow-sm p-6 border">
              <h2 className="text-2xl font-semibold text-gray-100 mb-4">{en ? HELP_EN.firstStepsTitle : 'Primeros pasos: modelo → tesis → decisión'}</h2>
              <ol className="space-y-4 text-gray-200">
                {en ? <FirstStepsEn /> : (<>
                <li>
                  <strong className="text-teal-400">1. Modelo.</strong>{' '}
                  En <Link href="/research" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">Research</Link> elige
                  la compañía y abre la pestaña «Modelo» y pulsa «Generar modelo». Revisa los supuestos (crecimiento, margen
                  FCF, WACC) y los escenarios Bear/Base/Bull con sus spreads antes de fiarte del número.
                </li>
                <li>
                  <strong className="text-teal-400">2. Tesis.</strong>{' '}
                  Genera la tesis desde la misma ficha: hipótesis, escenarios con probabilidades, catalizadores con
                  fecha y qué la invalidaría. El memo y el EPUB se exportan desde la propia vista de tesis
                  («Exportar memo» y «Exportar EPUB»);{' '}
                  <Link href="/export" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">/export</Link>{' '}
                  es la exportación anual del journal.
                </li>
                <li>
                  <strong className="text-teal-400">3. Decisión.</strong>{' '}
                  Registra la decisión en el Diario de decisiones (Comprar / Mantener / Reducir / Vender / Vigilar / Evitar) con la
                  evidencia que la justifica y las condiciones verificables («Qué debe cumplirse»). Más adelante,
                  «Expectativa vs realidad» compara tu previsión con los hechos publicados.
                </li>
                </>)}
              </ol>
            </section>

            {/* Guía por módulo */}
            <section className="bg-gray-800 rounded-lg shadow-sm p-6 border">
              <h2 className="text-2xl font-semibold text-gray-100 mb-4">{en ? HELP_EN.moduleGuideTitle : 'Guía por módulo'}</h2>
              <div className="grid md:grid-cols-2 gap-4">
                {(en ? MODULES_EN : modules).map((module) => (
                  <div className="bg-gray-900/40 p-4 rounded-lg" key={module.title}>
                    <h3 className="font-semibold text-teal-400 mb-2">
                      <Link href={module.href} className="underline underline-offset-4 hover:text-teal-300">
                        {module.title}
                      </Link>
                    </h3>
                    <p className="text-gray-300 text-sm">{module.text}</p>
                  </div>
                ))}
              </div>
            </section>

            {/* Glosario y metodología */}
            <section className="bg-gray-800 rounded-lg shadow-sm p-6 border">
              <h2 className="text-2xl font-semibold text-gray-100 mb-4">{en ? HELP_EN.glossaryTitle : 'Glosario y metodología'}</h2>
              <p className="text-gray-200 mb-4">
                {en ? <GlossaryEn /> : (<>
                Los términos técnicos (DCF, WACC, reverse DCF, moat, margen de seguridad, look-ahead, owner earnings,
                TAM/SAM/SOM, ROIC, VaR, drawdown, Sharpe) llevan un tooltip con su definición dondequiera que aparecen.
                Los motores de valoración con sus supuestos, las fuentes de datos (Finnhub, Yahoo Finance, SEC EDGAR),
                los límites y los costes están documentados en{' '}
                <Link href="/metodologia" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">
                  /metodologia
                </Link>.
                </>)}
              </p>
            </section>
          </div>
        </TabsContent>

        {/* Community Tab */}
        <TabsContent value="community" className="mt-0">
          <section className="bg-gradient-to-r from-blue-900/50 to-purple-900/50 rounded-lg p-8 text-center">
            <h2 className="text-2xl font-bold text-gray-100 mb-4">{en ? HELP_EN.contactTitle : 'Contacto'}</h2>
            <p className="text-gray-300 mb-6">
              {SUPPORT_EMAIL
                ? (en ? HELP_EN.contactWithEmail : '¿Tienes preguntas o sugerencias? Escríbenos por email.')
                : (en ? HELP_EN.contactNoEmail : '¿Tienes preguntas o sugerencias? El canal de contacto se publicará aquí.')}
            </p>
            {SUPPORT_EMAIL && (
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <a
                    href={`mailto:${SUPPORT_EMAIL}`}
                    className="bg-gray-800 text-gray-200 px-6 py-3 rounded-lg hover:bg-gray-700 transition-colors text-center inline-block"
                >
                    {en ? HELP_EN.emailTo : 'Enviar email a'} {SUPPORT_EMAIL}
                </a>
            </div>
            )}
          </section>
        </TabsContent>
      </Tabs>
    </main>
  );
}

