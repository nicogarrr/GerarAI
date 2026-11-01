/**
 * Glosario educativo de GerarAI.
 *
 * Cada entrada explica un concepto de inversión/valoración en 2-3 líneas
 * didácticas en español. Se consume desde tooltips (components/GlossaryTerm)
 * y desde /metodologia, para que el usuario aprenda inversión con la app.
 */

// @ts-expect-error TS5097: node --experimental-strip-types necesita la extensión.
import { DEFAULT_LOCALE, type Locale } from './i18n/locale.ts';

export type GlossaryKey =
  | 'dcf'
  | 'wacc'
  | 'reverse_dcf'
  | 'moat'
  | 'margen_seguridad'
  | 'look_ahead'
  | 'owner_earnings'
  | 'tam'
  | 'sam'
  | 'som'
  | 'bear'
  | 'base'
  | 'bull'
  | 'roic'
  | 'var'
  | 'drawdown'
  | 'sharpe'
  | 'moat_network_effects'
  | 'moat_switching_costs'
  | 'moat_cost_advantage'
  | 'moat_scale_economies'
  | 'moat_distribution'
  | 'moat_brand'
  | 'moat_regulation'
  | 'moat_data'
  | 'moat_ecosystem'
  | 'moat_capital_barrier'
  | 'moat_process_advantage';

export interface GlossaryEntry {
  /** Etiqueta visible corta (se muestra en el tooltip como título). */
  term: string;
  /** Definición didáctica en 2-3 líneas. */
  short: string;
}

export const glossary: Record<GlossaryKey, GlossaryEntry> = {
  dcf: {
    term: 'DCF (flujo de caja descontado)',
    short:
      'Valora una empresa descontando el flujo de caja libre que espera generar en el futuro hasta hoy, con una tasa que refleja su riesgo. Es el motor central de la valoración: cambia con tus supuestos de crecimiento, margen y WACC, no es un precio objetivo fijo. Úsalo como rango de escenarios, nunca como cifra exacta.',
  },
  wacc: {
    term: 'WACC (coste medio ponderado de capital)',
    short:
      'La tasa de descuento: lo que exigen conjuntamente accionistas y prestamistas por financiar la empresa, ponderado por su estructura de capital. A mayor riesgo o deuda más cara, mayor WACC y menor valor presente. En horizontes largos, un punto de WACC mueve el valor de forma notable.',
  },
  reverse_dcf: {
    term: 'Reverse DCF',
    short:
      'Da la vuelta al DCF: en vez de estimar el valor, parte del precio actual y calcula qué crecimiento o margen está descontando ya el mercado. Si lo que exige el precio es inverosímil frente a tu escenario base, la acción está cara (o barata). Es la forma más honesta de contrastar tus supuestos contra el precio.',
  },
  moat: {
    term: 'Moat (foso competitivo)',
    short:
      'La ventaja que protege los beneficios de la competencia durante años, clasificable en tipos (efectos de red, costes de cambio, marca…). Hay que justificarlo con evidencia concreta, no de oídas. Sin moat sostenible, un ROIC alto atrae rivales y se erosiona.',
  },
  margen_seguridad: {
    term: 'Margen de seguridad',
    short:
      'La diferencia entre lo que pagas y tu estimación de valor intrínseco, en %: el colchón para cuando te equivoques. A mayor incertidumbre del negocio, exige más margen (30%+ en casos duros). No evita pérdidas, limita el daño si la tesis falla.',
  },
  look_ahead: {
    term: 'Look-ahead bias (sesgo de mirar al futuro)',
    short:
      'Error de usar información que aún no existía en la fecha analizada, como resultados publicados después o datos retroactivamente revisados. Infla artificialmente cualquier backtest y cualquier tesis. GerarAI solo usa datos disponibles en cada fecha simulada para evitarlo.',
  },
  owner_earnings: {
    term: 'Owner earnings',
    short:
      'Lo que el dueño puede sacar realmente del negocio: beneficio neto + amortizaciones − capex de mantenimiento − variación de capital circulante (definición de Buffett). Más honesto que el beneficio contable porque descuenta lo que hay que reinvertir para no perder posición.',
  },
  tam: {
    term: 'TAM (Total Addressable Market)',
    short:
      'El mercado total: la demanda máxima si tuvieses el 100% del mercado global. Es el techo teórico y por sí solo dice poco; piénsalo siempre junto con SAM y SOM.',
  },
  sam: {
    term: 'SAM (Serviceable Addressable Market)',
    short:
      'El mercado alcanzable: la parte del TAM a la que tu producto y tus geografías pueden llegar realmente. Es el mercado sobre el que tiene sentido planificar a medio plazo.',
  },
  som: {
    term: 'SOM (Serviceable Obtainable Market)',
    short:
      'El mercado obtenible: la porción del SAM que puedes capturar en unos años con tu capacidad real (ventas, canales, competencia). Es el número que de verdad importa para valorar la empresa.',
  },
  bear: {
    term: 'Escenario Bear (pesimista)',
    short:
      'El caso adverso: ejecución por debajo, márgenes bajo presión y capital más caro. No es un cataclismo arbitrario: el precio corriendo con una prima de riesgo. Úsalo para medir cuánto puedes perder si la tesis se tuerce.',
  },
  base: {
    term: 'Escenario base (central)',
    short:
      'El caso más probable con supuestos normalizados: crecimiento y margen en línea con lo histórico de la compañía. Es el ancla de la valoración, pero no «el» valor: la realidad casi nunca coincide al punto.',
  },
  bull: {
    term: 'Escenario Bull (optimista)',
    short:
      'El caso favorable: ejecución por encima, expansión de margen y capital más barato. Exige que cada punto extra esté justificado, soñar no es un supuesto. Sirve para ver cuánto pagas hoy por el optimismo.',
  },
  roic: {
    term: 'ROIC (retorno del capital invertido)',
    short:
      'Beneficio operativo después de impuestos sobre el capital invertido en el negocio. Compáralo con el WACC: si ROIC > WACC la empresa crea valor; si es menor, lo destruye aunque crezca. Es la mejor radiografía de la calidad del crecimiento.',
  },
  var: {
    term: 'VaR (Value at Risk)',
    short:
      'Pérdida máxima esperada en un horizonte dado con un nivel de confianza (p. ej. un 5% de probabilidad de perder más de X en un mes). No cubre el peor caso, solo un umbral estadístico. Requiere historia y supuestos de distribución: es una estimación, no una promesa.',
  },
  drawdown: {
    term: 'Drawdown (caída máxima)',
    short:
      'La peor caída desde un máximo histórico hasta el siguiente mínimo, en %. Mide el dolor real que habría soportado el inversor, no solo la volatilidad. Un −40% exige un +67% para volver al punto de partida.',
  },
  sharpe: {
    term: 'Ratio de Sharpe',
    short:
      'Rentabilidad por encima del tipo libre de riesgo dividida por la volatilidad: cuánto retorno ganas por cada unidad de riesgo. Cuanto mayor, mejor compensado está el riesgo. Depende de la ventana elegida: dos periodos distintos dan ranking distinto.',
  },
  moat_network_effects: {
    term: 'Moat: efectos de red',
    short:
      'El producto gana valor con cada usuario nuevo (pagos, marketplaces, redes sociales). Una vez alcanzada la masa crítica es difícil de desplazar, pero ojo: la red puede migrar si pierde utilidad.',
  },
  moat_switching_costs: {
    term: 'Moat: costes de cambio',
    short:
      'Cambiar a un competidor cuesta al cliente tiempo, dinero o riesgo operativo (integraciones, datos acumulados, reentrenamiento). La fidelidad no es amor: es fricción. Mide cuánto tardaría un cliente real en irse.',
  },
  moat_cost_advantage: {
    term: 'Moat: ventaja de coste',
    short:
      'Produce lo mismo a un coste unitario menor de forma sostenida (procesos, materias primas, localización). Permite ganar cuota o margen con precios iguales. Solo es moat si el rival no puede replicarla con capex.',
  },
  moat_scale_economies: {
    term: 'Moat: economías de escala',
    short:
      'Al ser mayor, reparte costes fijos sobre más unidades y baja el coste medio. Funciona sobre todo donde los costes fijos son altos (industria, software). El pequeño puede ganar si el mercado se fragmenta.',
  },
  moat_distribution: {
    term: 'Moat: distribución',
    short:
      'Llega al cliente donde los rivales no llegan: acuerdos de canal, red propia o base instalada. Una gran idea sin canal no vende. Especialmente valiosa en consumidor y retail.',
  },
  moat_brand: {
    term: 'Moat: marca e intangibles',
    short:
      'El cliente paga más o elige primero por confianza, patentes o licencias. Aunque copien el producto, no copian la percepción. Se mantiene con consistencia durante años y se pierde con un solo escándalo.',
  },
  moat_regulation: {
    term: 'Moat: barreras regulatorias',
    short:
      'Licencias, concesiones o normas que limitan quién puede competir (banca, seguros, espectro, farmacia). Protege mucho, pero depende del regulador: un cambio de norma puede volar el foso de la noche a la mañana.',
  },
  moat_data: {
    term: 'Moat: ventaja de datos',
    short:
      'Datos exclusivos y masivos mejoran el producto, y el producto mejor atrae más datos: un bucle virtuoso difícil de replicar. Vigila la privacidad, la regulación puede cortar el bucle.',
  },
  moat_ecosystem: {
    term: 'Moat: ecosistema',
    short:
      'Familia de productos y servicios que se refuerzan entre sí (hardware + software + servicios). Cambiar de un producto arrastra a los demás. Más fuerte que un producto suelto, pero exige integración constante.',
  },
  moat_capital_barrier: {
    term: 'Moat: barrera de capital',
    short:
      'Competir exige una inversión inicial tan grande que pocos pueden permitírsela (fábricas, flotas, constelaciones satelitales). No protege si el capital llega barato: vigila el ciclo crediticio.',
  },
  moat_process_advantage: {
    term: 'Moat: ventaja de proceso',
    short:
      'Un método propio de fabricación o entrega mejor y difícil de imitar (el toyotismo, la litografía de semiconductores). No es un secreto puntual: es una organización que ejecuta mejor cada año.',
  },
};

/** Glosario en inglés (Ajustes → Idioma = English). Mismas claves que `glossary`. */
export const glossaryEn: Record<GlossaryKey, GlossaryEntry> = {
  dcf: {
    term: "DCF (discounted cash flow)",
    short:
      "Values a company by discounting the free cash flow it is expected to generate back to today, at a rate that reflects its risk. It is the core of the valuation: it moves with your growth, margin and WACC assumptions, so it is a range of scenarios rather than a fixed price target. Never treat it as an exact figure.",
  },
  wacc: {
    term: "WACC (weighted average cost of capital)",
    short:
      "The discount rate: what shareholders and lenders together require for financing the company, weighted by its capital structure. More risk or costlier debt means a higher WACC and a lower present value. Over long horizons, one point of WACC moves the value a lot.",
  },
  reverse_dcf: {
    term: "Reverse DCF",
    short:
      "Turns the DCF around: instead of estimating value, it starts from today's price and works out what growth or margin the market is already pricing in. If what the price requires is implausible against your base case, the stock is expensive (or cheap). It is the most honest way to test your assumptions against the price.",
  },
  moat: {
    term: "Moat (competitive advantage)",
    short:
      "The advantage that shields profits from competition for years, grouped into types (network effects, switching costs, brand…). It must be backed by concrete evidence, never by hearsay. Without a durable moat, a high ROIC attracts rivals and erodes.",
  },
  margen_seguridad: {
    term: "Margin of safety",
    short:
      "The gap between what you pay and your estimate of intrinsic value, in %: the cushion for when you are wrong. The more uncertain the business, the more margin you should demand (30%+ in hard cases). It does not prevent losses; it limits the damage if the thesis fails.",
  },
  look_ahead: {
    term: "Look-ahead bias",
    short:
      "The mistake of using information that did not yet exist on the date being analysed, such as results published later or data revised after the fact. It artificially inflates any backtest and any thesis. GerarAI only uses data that was available on each simulated date to avoid it.",
  },
  owner_earnings: {
    term: "Owner earnings",
    short:
      "What the owner can actually take out of the business: net income + depreciation and amortisation − maintenance capex − change in working capital (Buffett's definition). More honest than accounting profit because it subtracts what must be reinvested just to hold position.",
  },
  tam: {
    term: "TAM (Total Addressable Market)",
    short:
      "The total market: maximum demand if you had 100% of the global market. It is the theoretical ceiling and says little on its own; always read it together with SAM and SOM.",
  },
  sam: {
    term: "SAM (Serviceable Addressable Market)",
    short:
      "The reachable market: the part of the TAM your product and your geographies can actually reach. It is the market worth planning around in the medium term.",
  },
  som: {
    term: "SOM (Serviceable Obtainable Market)",
    short:
      "The obtainable market: the share of the SAM you can capture within a few years with your real capacity (sales, channels, competition). It is the number that really matters for valuing the company.",
  },
  bear: {
    term: "Bear case (pessimistic)",
    short:
      "The adverse case: weaker execution, margins under pressure and costlier capital. It is a price carrying a risk premium, not an arbitrary catastrophe. Use it to gauge how much you could lose if the thesis goes wrong.",
  },
  base: {
    term: "Base case (central)",
    short:
      "The most likely case with normalised assumptions: growth and margin in line with the company's history. It anchors the valuation but it is not «the» value: reality almost never matches it exactly.",
  },
  bull: {
    term: "Bull case (optimistic)",
    short:
      "The favourable case: stronger execution, margin expansion and cheaper capital. Every extra point must be justified; wishful thinking is not an assumption. It shows how much you are paying today for optimism.",
  },
  roic: {
    term: "ROIC (return on invested capital)",
    short:
      "After-tax operating profit divided by the capital invested in the business. Compare it with WACC: if ROIC > WACC the company creates value; if it is lower, it destroys value even while growing. It is the best X-ray of growth quality.",
  },
  var: {
    term: "VaR (Value at Risk)",
    short:
      "The maximum expected loss over a given horizon at a confidence level (e.g. a 5% chance of losing more than X in a month). It does not cover the worst case, only a statistical threshold. It needs history and distribution assumptions: an estimate, never a promise.",
  },
  drawdown: {
    term: "Drawdown (maximum decline)",
    short:
      "The worst fall from a peak to the next trough, in %. It measures the real pain an investor would have endured, beyond volatility. A −40% fall needs a +67% gain to get back to where it started.",
  },
  sharpe: {
    term: "Sharpe ratio",
    short:
      "Return above the risk-free rate divided by volatility: how much return you earn per unit of risk. The higher, the better the risk is rewarded. It depends on the chosen window: two different periods give different rankings.",
  },
  moat_network_effects: {
    term: "Moat: network effects",
    short:
      "The product gains value with every new user (payments, marketplaces, social networks). Once it reaches critical mass it is hard to displace, but beware: the network can move if it loses usefulness.",
  },
  moat_switching_costs: {
    term: "Moat: switching costs",
    short:
      "Moving to a competitor costs the customer time, money or operational risk (integrations, accumulated data, retraining). Loyalty is friction, not love. Measure how long a real customer would take to leave.",
  },
  moat_cost_advantage: {
    term: "Moat: cost advantage",
    short:
      "Producing the same thing at a lower unit cost, sustainably (processes, raw materials, location). It lets the company gain share or margin at equal prices. It is only a moat if rivals cannot replicate it with capex.",
  },
  moat_scale_economies: {
    term: "Moat: economies of scale",
    short:
      "Being bigger spreads fixed costs over more units and lowers the average cost. It works best where fixed costs are high (industry, software). A smaller player can win if the market fragments.",
  },
  moat_distribution: {
    term: "Moat: distribution",
    short:
      "Reaching customers where rivals cannot: channel agreements, an own network or an installed base. A great idea without a channel does not sell. Especially valuable in consumer and retail.",
  },
  moat_brand: {
    term: "Moat: brand and intangibles",
    short:
      "Customers pay more or choose first because of trust, patents or licences. Even if the product is copied, the perception is not. It is kept with years of consistency and lost with a single scandal.",
  },
  moat_regulation: {
    term: "Moat: regulatory barriers",
    short:
      "Licences, concessions or rules that limit who can compete (banking, insurance, spectrum, pharma). Strong protection, but it depends on the regulator: a rule change can wipe out the moat overnight.",
  },
  moat_data: {
    term: "Moat: data advantage",
    short:
      "Exclusive, large-scale data improves the product, and a better product attracts more data: a virtuous loop that is hard to replicate. Watch privacy rules, since regulation can break the loop.",
  },
  moat_ecosystem: {
    term: "Moat: ecosystem",
    short:
      "A family of products and services that reinforce each other (hardware + software + services). Leaving one product drags the others along. Stronger than a standalone product, but it needs constant integration.",
  },
  moat_capital_barrier: {
    term: "Moat: capital barrier",
    short:
      "Competing requires an upfront investment so large that few can afford it (factories, fleets, satellite constellations). It offers little protection when capital is cheap: watch the credit cycle.",
  },
  moat_process_advantage: {
    term: "Moat: process advantage",
    short:
      "A proprietary way of making or delivering things that is better and hard to imitate (the Toyota Production System, semiconductor lithography). It is an organisation that executes better every year, more than a one-off secret.",
  },
};

/** Glosario del idioma elegido (español por defecto). */
export function glossaryFor(locale: Locale = DEFAULT_LOCALE): Record<GlossaryKey, GlossaryEntry> {
  return locale === 'en' ? glossaryEn : glossary;
}

/** Mapea la clave canónica del backend (moat_framework.MOAT_CATEGORIES y afines) a su clave de glosario. */
export const moatGlossaryKey: Record<string, GlossaryKey> = {
  network_effects: 'moat_network_effects',
  switching_costs: 'moat_switching_costs',
  cost_advantage: 'moat_cost_advantage',
  scale_economies: 'moat_scale_economies',
  distribution: 'moat_distribution',
  intangible_assets: 'moat_brand',
  regulatory_barriers: 'moat_regulation',
  data_advantage: 'moat_data',
  ecosystem_lock_in: 'moat_ecosystem',
  capital_intensity_barrier: 'moat_capital_barrier',
  process_advantage: 'moat_process_advantage',
  // Claves cortas que persiste moat_service (MOAT_CATEGORIES del backend).
  brand: 'moat_brand',
  scale: 'moat_scale_economies',
  regulation: 'moat_regulation',
  data: 'moat_data',
  ecosystem: 'moat_ecosystem',
  capital_barrier: 'moat_capital_barrier',
};

/** Etiqueta (español por defecto) para una clave de moat del backend; fallback legible si llega una clave desconocida. */
export function moatLabel(type: string, locale: Locale = DEFAULT_LOCALE): string {
  const key = Object.hasOwn(moatGlossaryKey, type) ? moatGlossaryKey[type] : undefined;
  return key ? glossaryFor(locale)[key].term.replace('Moat: ', '') : type.replaceAll('_', ' ');
}
