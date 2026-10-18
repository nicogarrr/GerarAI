import { Metadata } from 'next';
import Link from 'next/link';
import {
  BookOpen,
  Calculator,
  Database,
  FlaskConical,
  LineChart,
  Scale,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Target,
  TriangleAlert,
  Users,
  Wallet,
} from 'lucide-react';

import { GlossaryTerm } from '@/components/GlossaryTerm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export const dynamic = 'force-dynamic';
export const revalidate = 3600;

/**
 * Página pública: la metodología es el mejor argumento de confianza del
 * producto y tiene que poder leerse sin crear una cuenta. El noindex de
 * `app/layout.tsx` lo sobrescribe `app/(public)/layout.tsx`.
 */
export const metadata: Metadata = {
  title: 'Metodología',
  description:
    'Fuentes de datos, motores de valoración, límites y costes de GerarAI: de dónde sale cada dato y qué no debes esperar de la plataforma.',
  robots: { index: true, follow: true },
  alternates: { canonical: '/metodologia' },
};

const sources = [
  {
    icon: Database,
    title: 'Finnhub',
    text: 'Precios (quotes), perfiles de compañía (profile2) y búsqueda de símbolos, incluidos tickers poco comunes. Capa gratuita con API key: es la fuente principal de nombres y cotizaciones.',
    href: '/research',
    cta: 'Ver research',
  },
  {
    icon: LineChart,
    title: 'Yahoo Finance · chart API',
    text: 'Índices y futuros reales: S&P 500 (^GSPC), Nasdaq (^IXIC), Bitcoin (BTC-USD), oro (GC=F) y plata (SI=F). Sin API key y con caché de 60 s. Nunca un ETF etiquetado como índice.',
    href: '/',
    cta: 'Ver índices en la home',
  },
  {
    icon: Users,
    title: 'SEC EDGAR',
    text: 'Filings 10-K/10-Q y Form 4 (operaciones de insiders) directamente del regulador de EE. UU. Acceso público y gratuito: la fuente primaria de documentos.',
    href: '/insider',
    cta: 'Ver señales insider',
  },
];

const engines = [
  {
    title: 'Standard DCF (por defecto)',
    text: (
      <>
        DCF FCFF a 5 años sobre ingresos y margen FCF del último snapshot coherente: si falta el margen se deriva
        como FCF/ingresos (acotado a 1%-50%) y el crecimiento sale de los hechos o de un valor por defecto (acotado
        a -15%/+45%). El <GlossaryTerm k="wacc" icon={false}>WACC</GlossaryTerm> y el crecimiento terminal usan un
        valor por defecto etiquetado como tal; la deuda neta del snapshot resta al equity (la caja neta suma).
        Escenarios bear/base/bull, sensibilidad 3x3 crecimiento x WACC y{' '}
        <GlossaryTerm k="reverse_dcf" icon={false}>reverse DCF</GlossaryTerm> incluidos.
      </>
    ),
  },
  {
    title: 'Pre-revenue / especulativo (pre-FCF)',
    text: 'DCF a 5 años para empresas sin caja libre: ingresos mínimos de 1,0 (para que ~0 no rompa la matemática), margen 1%-40%, crecimiento por defecto del 20% (acotado a -15%/+60%) y WACC del 13% por defecto. Escenarios causales (retraso de ejecución o estrés de financiación, base, monetización acelerada) con dilución extra en el bear (>=15%, tope del 80% del valor) y funding gap estimado a 2 años con buffer del 50%.',
  },
  {
    title: 'Commodities (minería, energía, uranio)',
    text: 'Flujo = max(precio - coste unitario, 0) x volumen x (1 - tasa), y equity = flujo x múltiplo - deuda neta, todo desde hechos financieros (precio realizado o spot, coste, volumen, múltiplo). Los escenarios son el grid de precios x0,75 / x1,0 / x1,25 sobre el precio de referencia, y esa misma tabla es la sensibilidad.',
  },
  {
    title: 'SOTP (multi-segmento)',
    text: 'NAV = suma de (métrica operativa del segmento x múltiplo del segmento) - deuda neta, con contrato explícito de hechos por segmento y descuento holding entre 0 y 1. Escenarios: descuento +15pp (techo 45%) / base / -8pp con NAV x1,12 en el bull; sensibilidad del descuento -5pp / base / +5pp. Nunca cae a un DCF de firma única.',
  },
  {
    title: 'Holding company (tipo BN/BABA)',
    text: 'Para holdings: hereda el SOTP con descuento holding explícito que recoge el conglomerate discount persistente del grupo. Mismos escenarios y misma sensibilidad del descuento que el SOTP.',
  },
];

const steps = [
  {
    title: 'Métricas de calidad y crecimiento',
    text: 'Rentabilidad, flujo de caja, crecimiento y salud de balance, calculadas sobre los filings persistidos. La valoración (FCF/earnings yield) y el momentum aún no puntúan en v1: lo declara el embudo de abajo.',
  },
  {
    title: 'Ranking por percentiles del universo',
    text: 'Cada componente se convierte a percentil sobre todo el universo persistido y se pondera con pesos declarados; si un componente falta, los pesos se renormalizan y queda registrado.',
  },
  {
    title: 'Score + confianza verificable',
    text: 'Score 0-100 con nivel de confianza y motivos auditables: cada motivo muestra su métrica y su valor.',
  },
  {
    title: 'Backtesting walk-forward',
    text: 'Existe un backtest walk-forward global, pero es un baseline de momentum solo-precio: no es un backtest de ProPicks. El backtest por estrategia se publicará cuando existan fundamentales point-in-time; hasta entonces ninguna estrategia muestra desempeño simulado.',
  },
];

const limits = [
  {
    icon: TriangleAlert,
    title: 'Datos con retraso',
    text: 'Los datos de mercado llegan con ligero retraso en la mayoría de mercados. Suficiente para análisis, no para trading intradía.',
  },
  {
    icon: ShieldAlert,
    title: 'Cobertura parcial',
    text: 'No todos los tickers tienen la misma cobertura: si faltan filings o métricas, la ficha lo indica en lugar de inventar.',
  },
  {
    icon: Scale,
    title: 'Point-in-time',
    text: (
      <>
        Los motores de valoración solo usan información disponible en cada fecha simulada: sin mirar al futuro.
        Evitar el <GlossaryTerm k="look_ahead" icon={false}>look-ahead</GlossaryTerm> es lo que hace que un backtest
        sea creíble.
      </>
    ),
  },
  {
    icon: Target,
    title: 'No es asesoramiento',
    text: 'GerarAI es una herramienta educativa y de análisis. Las decisiones de inversión son siempre tuyas.',
  },
];

const costs = [
  {
    icon: Wallet,
    title: 'Datos: 0 EUR/mes',
    text: 'Finnhub (capa gratuita con key), Yahoo Finance (chart API sin key) y SEC EDGAR (acceso público). Las tres fuentes de datos activas son sin cuota.',
  },
  {
    icon: FlaskConical,
    title: 'Modelos LLM: por uso',
    text: 'OpenCode Go como único proveedor, con el precio por modelo publicado en model_aliases.py (coste real o "desconocido" explícito, nunca 0 silencioso). Las micro-decisiones van por el cliente Jev (~0,042 USD/MTok de entrada, salida gratuita) con presupuesto objetivo por debajo de 0,50 USD/mes.',
  },
  {
    icon: BookOpen,
    title: 'Infraestructura: autoalojada',
    text: 'Frontend en Vercel (plan hobby); backend autoalojado con Postgres, Qdrant, MinIO y Redis en la máquina propia. Sin cuota cloud: solo energía y hardware del host.',
  },
];

export default function MetodologiaPage() {
  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-6 overflow-x-clip px-4 py-10 md:px-6 lg:px-8">
      <header className="flex flex-col gap-4 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase text-teal-300">Transparencia</p>
          <h1 className="mt-1 break-words text-2xl font-bold text-gray-100 sm:text-3xl">Metodología</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">
            Fuentes, motores de valoración, límites y costes de GerarAI: de dónde sale cada dato, cómo se
            calcula cada número y qué no debes esperar de la plataforma.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline">
            <Link href="/knowledge">
              <BookOpen className="h-4 w-4" />
              Knowledge
            </Link>
          </Button>
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline">
            <Link href="/search">
              <Search className="h-4 w-4" />
              Buscar evidencia
            </Link>
          </Button>
          <Button asChild className="h-11 w-full sm:w-auto">
            <Link href="/propicks">
              <Sparkles className="h-4 w-4" />
              Ver ProPicks
            </Link>
          </Button>
        </div>
      </header>

      {/* La página es pública, pero los módulos que enlaza viven dentro de la
          app: se dice aquí, en vez de dejar que un visitante sin cuenta
          descubra el muro de sesión al pulsarlos. */}
      <p className="rounded-xl border border-gray-700/50 bg-surface-overlay p-4 text-sm leading-6 text-gray-300">
        Esta página es pública. Los botones y las fichas que enlazan (research, índices, señales de
        insiders, Knowledge, búsqueda de evidencia y ProPicks) forman parte del espacio de trabajo:
        requieren una cuenta, así que al pulsarlos se te pedirá iniciar sesión.{' '}
        <Link href="/sign-up" className="public-footer-link">
          Crear cuenta
        </Link>{' '}
        o{' '}
        <Link href="/sign-in" className="public-footer-link">
          iniciar sesión
        </Link>
        .
      </p>

      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Database className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Fuentes de datos</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {sources.map((source) => (
            <article
              className="flex min-w-0 flex-col rounded-xl border border-gray-800 bg-surface-1 p-4 break-words sm:p-5"
              key={source.title}
            >
              <div className="flex items-center gap-2">
                <source.icon className="h-5 w-5 shrink-0 text-teal-300" />
                <h3 className="font-semibold text-gray-100">{source.title}</h3>
              </div>
              <p className="mt-2 flex-1 text-sm leading-6 text-gray-400">{source.text}</p>
              <Button asChild className="mt-4 h-11 w-full sm:w-fit" size="sm" variant="outline">
                <Link href={source.href}>{source.cta}</Link>
              </Button>
            </article>
          ))}
        </div>
        <p className="mt-4 rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-sm leading-6 text-amber-200">
          <strong>FMP solo cubre mercado US:</strong> el plan gratuito de Financial Modeling Prep quedó limitado a
          compañías US (sus endpoints antiguos responden &laquo;Legacy Endpoint&raquo; o 402 fuera de ese mercado).
          La API acepta el refresco con FMP para cualquier emisor, pero fuera de US el proveedor lo rechaza y el
          refresco falla con aviso. No hay sustitución automática: si el emisor reporta a SEC EDGAR o ESEF,
          puedes lanzar tú el refresco desde esas fuentes (acción separada en la ficha); y si ninguna fuente
          cubre al emisor, los financieros se muestran como no disponibles en lugar de estimarse.
          En el refresco de precios del backend, los listados US se consultan primero en FMP si hay clave y la
          cotización trae fecha válida; Finnhub es el fallback. Yahoo Finance aporta el refresco intradía de cartera
          y las series históricas de ProPicks, también para listados no-US cuando el símbolo de su bolsa se conoce.
          Sin cotización o símbolo fiable, se muestra sin precio.
        </p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <h2 className="text-lg font-semibold text-gray-100">Señal orbital AST: semieje mayor</h2>
        <p className="mt-2 text-sm leading-6 text-gray-400">Para cada objeto del grupo AST de CelesTrak calculamos el semieje mayor con
          a = (μ / (2πn / 86.400)²)^(1/3), con μ terrestre = 398.600,4418 km³/s² y n en revoluciones al día.
          Conservamos hasta 32 épocas distintas por ID NORAD. Comparamos solo una ventana de 24 a 72 horas
          con al menos tres épocas separadas por dos horas. Una caída de 2 km o más invita a revisar fuentes,
          no prueba despliegue, maniobra ni causa: la resistencia atmosférica, ajustes orbitales y revisiones
          de elementos también pueden producir cambios. BSTAR y las derivadas del movimiento medio son
          parámetros de ajuste, no telemetría independiente. La señal es exploratoria y no sustituye
          una confirmación primaria. El grupo AST se consulta cada dos horas como máximo. GP (catálogo general) y SupGP (elementos
          suplementarios AST-E) se guardan y representan en series independientes: no se comparan entre sí.
          Una fuente puede faltar sin invalidar la otra. Nunca se consulta CelesTrak al abrir la vista;
          después de 30 horas sin descarga válida se ocultan señal e historial caducados de cada fuente.
          La época orbital y la fecha de descarga son distintas.</p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Calculator className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Motores de valoración</h2>
          <Badge className="sm:ml-auto" variant="outline">
            5 motores
          </Badge>
        </div>
        <p className="mb-4 text-sm leading-6 text-gray-400">
          Cada compañía se valora con el motor que le corresponde por su tipo y factor tags; los supuestos de abajo
          son los reales del código (data-engine/app/valuation/engines/), no una descripción de marketing. Cuando
          falta un dato obligatorio el motor devuelve insufficient_data en lugar de inventar un número.
        </p>
        <ol className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {engines.map((engine, index) => (
            <li
              className="flex min-w-0 gap-3 rounded-lg border border-gray-800 bg-black/30 p-4 break-words"
              key={engine.title}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-950 text-sm font-semibold text-teal-300">
                {index + 1}
              </span>
              <div className="min-w-0">
                <h3 className="font-semibold text-gray-100">{engine.title}</h3>
                <p className="mt-1 text-sm leading-6 text-gray-400">{engine.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-xs leading-5 text-gray-500">
          Además existen motores sectoriales dedicados para bancos (P/B justificado = (ROE - g)/(CoE - g)),
          aseguradoras (el mismo P/B multiplicado por un factor del combined ratio) e inmobiliarias cotizadas (REIT).
          Los escenarios bear/base/bull de cada motor se muestran con sus supuestos en la ficha de la compañía,
          dentro de &laquo;Supuestos del escenario&raquo;.
        </p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Sparkles className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Cómo se generan los ProPicks</h2>
          <Badge className="sm:ml-auto" variant="outline">
            4 pasos
          </Badge>
        </div>
        <ol className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {steps.map((step, index) => (
            <li
              className="flex min-w-0 gap-3 rounded-lg border border-gray-800 bg-black/30 p-4 break-words"
              key={step.title}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-950 text-sm font-semibold text-teal-300">
                {index + 1}
              </span>
              <div className="min-w-0">
                <h3 className="font-semibold text-gray-100">{step.title}</h3>
                <p className="mt-1 text-sm leading-6 text-gray-400">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-4 rounded-xl border border-teal-900/60 bg-teal-950/20 p-4 text-sm leading-6 text-teal-100">
          <strong>GerarAI ProPicks:</strong> la selección v1 puntúa calidad, rentabilidad, flujo de
          caja y crecimiento por percentiles sobre todo el universo persistido. La valoración
          (FCF yield / earnings yield) y el momentum aún no entran en el embudo v1: las series de
          precios solo se persisten para el top-N tras cada run, no para todo el universo. De las cuatro estrategias (adaptativa, value, momentum y
          defensiva), cada ficha declara su estado real: si aún no tiene selección o backtest
          publicados, lo dice en lugar de mostrar estimaciones.
        </p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Search className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">
            Embudo ProPicks (etapa big-data, v1)
          </h2>
          <Badge className="sm:ml-auto" variant="outline">
            propicks-funnel-v1
          </Badge>
        </div>
        <div className="space-y-3 text-sm leading-6 text-gray-400">
          <p>
            El embudo evalúa <strong className="text-gray-200">todo el universo persistido</strong>{' '}
            (2.110 empresas: SEC + ESEF) con métricas ya calculadas en base de datos. Nada se
            imputa: cada empresa lleva su mapa de cobertura por métrica (ok / missing / approx) y
            el motivo exacto de cada filtro que no supera.
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="text-gray-200">Cobertura mínima:</strong> al menos 6 de las 9
              métricas de calidad (ROIC, CFROI aproximado, FCF margin 5y, owner earnings 5y,
              márgenes 5y, ROE 5y, ROA 5y, capex/DA, MOAT V2).
            </li>
            <li>
              <strong className="text-gray-200">Consistencia de beneficios</strong> (Graham /
              Buffett): beneficio neto positivo en al menos 4 de los últimos 5 ejercicios con
              datos; con menos de 4 años de datos no hay evidencia suficiente.
            </li>
            <li>
              <strong className="text-gray-200">Deuda:</strong> ND/EBITDA &lt; 3 cuando la métrica
              existe (hoy cobertura US; en EUR se declara missing y no se aplica, nunca se inventa).
            </li>
            <li>
              <strong className="text-gray-200">Filtro de calidad por rama sectorial:</strong> el
              ROIC/CFROI no es significativo en bancos y aseguradoras (Greenblatt las excluye de la
              Magic Formula por la misma razón). Financieras: ROE 5y &gt; coste de equity, con la
              aproximación declarada de usar el WACC almacenado como proxy del coste de equity.
              Resto: ROIC &gt; WACC y CFROI &gt; WACC.
            </li>
            <li>
              <strong className="text-gray-200">Ranking:</strong> cada componente se convierte a
              percentil sobre el universo y se pondera: spread ROIC-WACC 25%, spread CFROI-WACC
              15%, MOAT V2 20%, ROE 5y 10%, FCF margin 5y 10%, crecimiento de ingresos (CAGR) 10%,
              owner earnings 5y 5%, conversión FCF 5%. Si un componente no aplica o falta, los pesos
              se renormalizan y queda declarado.
            </li>
          </ul>
          <p>
            <strong className="text-gray-200">Lo que v1 NO incluye todavía:</strong> valoración
            (FCF yield / earnings yield) y momentum — el embudo v1 no los usa: las series de
            precios solo se persisten para el top-N tras cada run, no para todo el universo. Cada ejecución del embudo se guarda completa (runs y candidatos,
            incluidos los descartados con sus motivos), así que el histórico y el diff entra/sale
            son auditables.
          </p>
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Marco de calidad (MOAT)</h2>
          <Badge className="sm:ml-auto" variant="outline">
            Hasta 8 criterios
          </Badge>
        </div>
        <p className="mb-4 text-sm leading-6 text-gray-400">
          Estos ocho criterios describen calidad financiera histórica, no demuestran por sí solos
          un foso competitivo. Solo se puntúan en el perfil operativo general y con datos
          suficientes. Para empresas en etapa temprana o de crecimiento, financieras y cíclicas,
          no se muestra un 0/8 engañoso: el resultado es «no evaluable con estos umbrales».
          El perfil se basa en tipo, sector y etiquetas registrados, no en el ticker ni en pérdidas
          de un año. Cada valor subyacente permanece accesible como métrica individual. La
          evaluación del foso exige evidencia verificable por separado; su ausencia no equivale a cero.
        </p>
        <ul className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {[
            ['Margen FCF 5 años', 'media > 5%'],
            ['Margen neto 5 años', 'media > 15%'],
            ['ROE 5 años', 'media > 15%'],
            ['ROA 5 años', 'media > 7%'],
            ['ROIC', '> WACC'],
            ['CFROI (aprox. declarada)', '> WACC'],
            ['Owner earnings 5 años (Buffett)', 'media > 0'],
            ['Capex / D&A 5 años', 'media ≤ 1,5 (1,0 = solo mantenimiento)'],
          ].map(([check, threshold]) => (
            <li
              className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-gray-800 bg-black/30 p-4 break-words"
              key={check}
            >
              <span className="text-sm text-gray-200">{check}</span>
              <span className="shrink-0 text-sm font-semibold text-teal-300">{threshold}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 rounded-xl border border-teal-900/60 bg-teal-950/20 p-4 text-sm leading-6 text-teal-100">
          Los umbrales son ajustables: están definidos como constantes documentadas en el motor
          de métricas (metric_calculation_service.py) y aquí para revisarlos en cualquier
          momento. Owner earnings estima el capex de mantenimiento como min(|capex|, D&A), una
          aproximación conservadora declarada (Buffett, carta de 1986); el CFROI usa la
          aproximación declarada del sistema, no el CFROI completo de Credit Suisse.
        </p>
        <p className="mt-4 rounded-xl border border-gray-800 bg-black/30 p-4 text-sm leading-6 text-gray-400">
          Emisores ESEF (España/UE): IFRS reparte la deuda en varios tags y la metodología
          prohíbe sumarlos, así que ROIC y WACC estándar no son calculables. En su lugar el V2
          usa dos aproximaciones declaradas, ambas conservadoras contra el check: el WACC se
          calcula como coste de equity puro (cota superior del WACC real, umbral más exigente)
          y el capital invertido como activos − caja (cota superior del denominador, ROIC a la
          baja). Si una empresa no tiene datos suficientes, el check queda no evaluable aunque
          el grado sea alcanzable: nunca se maquilla.
        </p>
      </section>

      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-amber-300" />
          <h2 className="text-lg font-semibold text-gray-100">Límites que debes conocer</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {limits.map((limit) => (
            <article
              className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 break-words sm:p-5"
              key={limit.title}
            >
              <div className="flex items-center gap-2">
                <limit.icon className="h-5 w-5 shrink-0 text-amber-300" />
                <h3 className="font-semibold text-gray-100">{limit.title}</h3>
              </div>
              <p className="mt-2 text-sm leading-6 text-gray-400">{limit.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Wallet className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Costes explícitos</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-3">
          {costs.map((cost) => (
            <article
              className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 break-words sm:p-5"
              key={cost.title}
            >
              <div className="flex items-center gap-2">
                <cost.icon className="h-5 w-5 shrink-0 text-teal-300" />
                <h3 className="font-semibold text-gray-100">{cost.title}</h3>
              </div>
              <p className="mt-2 text-sm leading-6 text-gray-400">{cost.text}</p>
            </article>
          ))}
        </div>
        <p className="mt-4 rounded-xl border border-gray-800 bg-black/30 p-4 text-sm leading-6 text-gray-400">
          Fuentes, límites y costes se documentan aquí mismo, sin letra pequeña: lo que ves es lo que hay. Si un
          coste no se puede cuantificar, se dice &laquo;desconocido&raquo; en lugar de poner un 0 que rompería el
          presupuesto.
        </p>
      </section>
    </main>
  );
}
