/**
 * Glosario educativo de GerarAI.
 *
 * Cada entrada explica un concepto de inversión/valoración en 2-3 líneas
 * didácticas en español. Se consume desde tooltips (components/GlossaryTerm)
 * y desde /metodologia, para que el usuario aprenda inversión con la app.
 */

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

/** Etiqueta en español para una clave de moat del backend; fallback legible si llega una clave desconocida. */
export function moatLabel(type: string): string {
  const key = Object.hasOwn(moatGlossaryKey, type) ? moatGlossaryKey[type] : undefined;
  return key ? glossary[key].term.replace('Moat: ', '') : type.replaceAll('_', ' ');
}
