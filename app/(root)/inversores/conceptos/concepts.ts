/** Síntesis editorial en español. No citas literales ni principios extraídos por IA. */
export type InvestorConcept = {
  slug: string;
  title: string;
  summary: string;
  body: string;
  application: string;
  risk: string;
  investors: string[];
  source: { title: string; url: string };
};


const BERKSHIRE_1986 = {
  title: "Berkshire Hathaway · Carta de 1986",
  url: "https://www.berkshirehathaway.com/letters/1986.html",
};
const BERKSHIRE_1989 = {
  title: "Berkshire Hathaway · Carta de 1989",
  url: "https://www.berkshirehathaway.com/letters/1989.html",
};
const BERKSHIRE_2007 = {
  title: "Berkshire Hathaway · Carta de 2007",
  url: "https://www.berkshirehathaway.com/letters/2007ltr.pdf",
};
const BUFFETT_1996 = {
  title: "Berkshire Hathaway · Carta de 1996",
  url: "https://www.berkshirehathaway.com/letters/1996.html",
};
export const CONCEPTS: InvestorConcept[] = [
  {
    slug: "circulo-de-competencia",
    title: "Círculo de competencia",
    summary: "Entender un negocio importa más que seguir todos los negocios.",
    body: "Buffett distingue entre evaluar empresas seleccionadas y conocer todas las empresas. Lo importante es delimitar lo que entiendes, no ampliar el círculo a cualquier precio.",
    application:
      "Antes de valorar una empresa, identifica cómo gana dinero, qué sostiene su ventaja y qué podría cambiar ese negocio.",
    risk: "Conocer el producto no basta para entender sus costes, deuda o competencia.",
    investors: ["buffett"],
    source: BUFFETT_1996,
  },
  {
    slug: "ventaja-competitiva",
    title: "Ventaja competitiva duradera",
    summary:
      "Buscar una posición económica que pueda resistir el paso del tiempo.",
    body: "La carta de 1996 describe la preferencia de Berkshire por negocios cuya fortaleza competitiva pueda seguir existiendo muchos años después. El precio de compra sigue importando.",
    application:
      "Contrasta la ventaja con márgenes, retención de clientes, costes de cambio y capacidad de los rivales para replicarla.",
    risk: "Una empresa excelente puede ser una mala inversión si se paga demasiado. La ventaja también puede desaparecer.",
    investors: ["buffett"],
    source: BUFFETT_1996,
  },
  {
    slug: "paciencia",
    title: "Paciencia y seguimiento",
    summary:
      "Mantener un buen negocio no significa dejar de comprobar la tesis.",
    body: "Buffett compara mantener acciones con ser dueño de un negocio: comprar a un precio razonable y comprobar después si se conservan la calidad económica y la calidad de la dirección.",
    application:
      "Define las señales que invalidarían la tesis antes de comprar. Revisa el negocio, no solo las oscilaciones de su cotización.",
    risk: "La paciencia no justifica ignorar un deterioro permanente ni el riesgo de concentración.",
    investors: ["buffett"],
    source: BUFFETT_1996,
  },
  {
    slug: "opciones",
    title: "Opciones: calls y puts",
    summary: "Derechos para el comprador, obligaciones para el vendedor.",
    body: "Una call da al comprador el derecho a comprar el subyacente al precio de ejercicio; una put, el derecho a venderlo. El derecho tiene un vencimiento y cuesta una prima. El vendedor asume la obligación correspondiente cuando se ejerce.",
    application:
      "Compara el coste de la prima, el vencimiento, el precio de ejercicio y el tamaño real del contrato antes de abrir una posición.",
    risk: "El comprador puede perder toda la prima. Vender opciones puede exigir garantías y generar pérdidas superiores a la prima cobrada; una call vendida sin cobertura puede tener pérdidas ilimitadas.",
    investors: [],
    source: {
      title: "SEC · Introducción a las opciones",
      url: "https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-63",
    },
  },
  {
    slug: "wacc",
    title: "WACC (coste medio ponderado de capital)",
    summary: "La rentabilidad mínima que exige el capital invertido en la empresa.",
    body: "El WACC pondera el coste de los fondos propios y el de la deuda según su peso en la financiación. Es la tasa con la que se descuentan los flujos futuros y el listón que debe superar el ROIC para que la empresa cree valor. No es un dato observable: se construye con hipótesis (tipo libre de riesgo, beta, prima de riesgo, coste de la deuda) que conviene conocer antes de comparar.",
    application:
      "Compara el ROIC con el WACC antes de hablar de creación de valor y revisa las hipótesis del WACC que uses como tasa de descuento.",
    risk: "Dos analistas serios obtienen WACC distintos para la misma empresa: una beta o una prima de riesgo distinta cambia la valoración.",
    investors: [],
    source: {
      title: "Wikipedia · Weighted average cost of capital",
      url: "https://en.wikipedia.org/wiki/Weighted_average_cost_of_capital",
    },
  },
  {
    slug: "cfroi",
    title: "CFROI",
    summary: "Rentabilidad del flujo de caja sobre la inversión bruta realizada.",
    body: "El CFROI compara el flujo de caja bruto que genera una empresa con la inversión bruta realizada, con ajuste por inflación en la versión original de Credit Suisse HOLT. Busca medir la rentabilidad real del capital sin las distorsiones contables del beneficio. La versión completa exige datos que pocas empresas publican, por lo que en la práctica se calculan aproximaciones que deben declararse.",
    application:
      "Un CFROI sostenido por encima del coste de capital indica creación de valor; por debajo, la empresa destruye valor aunque el beneficio contable crezca.",
    risk: "Las aproximaciones no son comparables entre sí ni con el CFROI original si no se conoce la fórmula exacta usada.",
    investors: [],
    source: {
      title: "Wikipedia · Cash flow return on investment",
      url: "https://en.wikipedia.org/wiki/Cash_flow_return_on_investment",
    },
  },
  {
    slug: "foso-competitivo",
    title: "Foso competitivo (moat)",
    summary:
      "La ventaja que protege los beneficios frente a la competencia durante años.",
    body: "Buffett pidió en 2007 negocios con un foso duradero: una barrera que dificulta que los competidores les quiten rentabilidad. Marca, costes menores, costes de cambio, efectos de red, licencias o barreras de capital son formas habituales. El foso no es una lista de cualidades: es la respuesta a por qué este negocio seguirá ganando dinero dentro de diez años.",
    application:
      "Antes de valorar, identifica qué foso tiene la empresa, qué evidencia lo demuestra (retención, márgenes estables, cuota) y qué podría erosionarlo.",
    risk: "Los fosos se estrechan: la tecnología, la regulación o un mal equipo directivo pueden eliminar una ventaja que parecía permanente.",
    investors: ["buffett"],
    source: BERKSHIRE_2007,
  },
  {
    slug: "owner-earnings",
    title: "Beneficio del propietario (owner earnings)",
    summary: "La caja que el dueño puede extraer sin deteriorar el negocio.",
    body: "En la carta de 1986 Buffett definió el beneficio del propietario como el beneficio contable más depreciación y amortización, menos el capex medio que el negocio necesita para mantener su posición competitiva y su volumen, y las necesidades de capital circulante. Es su alternativa al beneficio neto para valorar. El capex de mantenimiento no se publica por separado: siempre es una estimación y hay que declarar la regla usada.",
    application:
      "Úsalo en lugar del beneficio neto cuando evalúes cuánta caja genera realmente un negocio para su dueño.",
    risk: "Si la estimación del capex de mantenimiento es demasiado baja, el beneficio del propietario queda inflado sin que nadie mienta.",
    investors: ["buffett"],
    source: BERKSHIRE_1986,
  },
  {
    slug: "capex-mantenimiento-crecimiento",
    title: "Capex de mantenimiento vs. de crecimiento",
    summary:
      "No toda la inversión es un coste: parte mantiene el negocio y parte lo expande.",
    body: "El capex de mantenimiento conserva la capacidad y la posición competitiva actuales; el capex de crecimiento busca más volumen o más margen. Las empresas casi nunca separan ambos en sus informes, así que distinguirlos exige una estimación declarada. La distinción cambia la valoración: solo el capex de mantenimiento es un coste inevitable; el de crecimiento puede ser una buena inversión si rinde por encima del coste de capital.",
    application:
      "Cuando una empresa invierte mucho, pregunta qué parte mantiene lo que ya existe y qué parte construye algo nuevo con rentabilidad esperada.",
    risk: "Un negocio que necesita reinvertir todo solo para no retroceder parece que crece cuando en realidad corre para quedarse en el mismo sitio.",
    investors: ["buffett"],
    source: BERKSHIRE_1986,
  },
  {
    slug: "trampa-de-valor",
    title: "Trampa de valor",
    summary: "Barato por múltiplos no es barato si el negocio se deteriora.",
    body: "Una trampa de valor es una acción que cotiza a múltiplos bajos porque el mercado descuenta un deterioro permanente: beneficios que caen, foso que desaparece, deuda que ahoga. El precio bajo es correcto, no una oportunidad. Para distinguirla de una ganga hay que comprobar que la generación de caja y la posición competitiva se mantienen.",
    application:
      "Antes de comprar algo muy barato, busca la razón del descuento y comprueba si el deterioro es temporal o permanente.",
    risk: "Que una acción haya caído mucho no es evidencia de nada: puede estar barata o puede estar empezando a descontar su declive.",
    investors: [],
    source: {
      title: "Investopedia · Value trap",
      url: "https://www.investopedia.com/terms/v/valuetrap.asp",
    },
  },
  {
    slug: "ciclo-economico",
    title: "Ciclo económico",
    summary:
      "Las fases de expansión y contracción que atraviesan a toda la economía.",
    body: "La actividad, el empleo y los beneficios empresariales se mueven en ciclos sin duración fija ni calendario predecible. Las empresas cíclicas amplifican ese vaivén; las defensivas lo atenúan. El ciclo importa al valorar: aplicar un múltiplo a los beneficios del mejor momento del ciclo sobreestima de forma permanente lo que la empresa puede ganar.",
    application:
      "En empresas cíclicas, normaliza los beneficios a lo largo de un ciclo completo antes de comparar múltiplos.",
    risk: "Confundir un pico de ciclo con crecimiento estructural lleva a pagar precios de crecimiento por negocios cíclicos.",
    investors: [],
    source: {
      title: "Wikipedia · Ciclo económico",
      url: "https://es.wikipedia.org/wiki/Ciclo_econ%C3%B3mico",
    },
  },
  {
    slug: "curva-de-tipos",
    title: "Curva de tipos de interés",
    summary: "La rentabilidad de la deuda pública según el plazo y lo que anticipa.",
    body: "La curva de tipos representa la rentabilidad de los bonos del Estado en cada vencimiento. Lo normal es que el largo plazo pague más que el corto; cuando se invierte, históricamente ha precedido a desaceleraciones, sin ser una señal mecánica. Recoge expectativas de tipos oficiales, inflación y prima de riesgo, y cambia cada día con los precios de los bonos.",
    application:
      "Úsala como contexto: una curva invertida encarece la financiación corta y suele coincidir con políticas monetarias restrictivas.",
    risk: "Predecir recesiones con la curva acumula falsos positivos; es contexto, no un calendario.",
    investors: [],
    source: {
      title: "Wikipedia · Curva de rendimiento",
      url: "https://es.wikipedia.org/wiki/Curva_de_rendimiento",
    },
  },
  {
    slug: "deflacion",
    title: "Deflación",
    summary: "La bajada sostenida de precios que encarece las deudas.",
    body: "La deflación es el descenso sostenido del nivel general de precios, no la bajada aislada de algunos bienes. Retrasa compras e inversiones y encarece la deuda en términos reales: el importe adeudado no baja mientras los ingresos sí. Por eso los bancos centrales la consideran más peligrosa que una inflación moderada y actúan para evitarla.",
    application:
      "En un entorno deflacionista, la deuda pesa más cada año: exige más caja real a empresas y familias endeudadas.",
    risk: "Confundir deflación con desinflación (precios que suben más despacio) cambia por completo el diagnóstico.",
    investors: [],
    source: {
      title: "Wikipedia · Deflación",
      url: "https://es.wikipedia.org/wiki/Deflaci%C3%B3n_(econom%C3%ADa)",
    },
  },
  {
    slug: "bancos-centrales",
    title: "Bancos centrales",
    summary: "Quienes fijan el precio oficial del dinero.",
    body: "Un banco central emite la moneda, fija los tipos de interés oficiales y persigue la estabilidad de precios y del sistema financiero; en la zona euro es el BCE y en Estados Unidos la Reserva Federal. Sus decisiones se transmiten al coste de la deuda, a la valoración de los activos y a la inflación. Conocer su mandato ayuda a entender por qué suben o bajan los tipos.",
    application:
      "Sigue los tipos oficiales y las guías del banco central como contexto de valoración: afectan a la tasa de descuento de todo lo demás.",
    risk: "La independencia formal no elimina errores de diagnóstico; sus previsiones también fallan.",
    investors: [],
    source: {
      title: "Banco de España · ¿Qué es un banco central?",
      url: "https://www.bde.es/wbe/es/areas-actuacion/politica-monetaria/preguntas-frecuentes/politica-monetaria-y-estabilidad-precios/que-es-banco-central.html",
    },
  },
  {
    slug: "compounder",
    title: "Compounder",
    summary: "La empresa que reinvierte bien una y otra vez.",
    body: "Un compounder es una empresa capaz de reinvertir sus beneficios a rentabilidades altas durante muchos años, de modo que su valor crece de forma compuesta. La clave no es solo crecer, sino que cada euro retenido rinda por encima de su coste de capital. Buffett resumió la idea en 1989: el tiempo es amigo del buen negocio y enemigo del mediocre.",
    application:
      "Busca negocios con ROIC alto y espacio para reinvertir; ahí el interés compuesto trabaja para el accionista.",
    risk: "Pagar cualquier precio por un compounder destruye la ventaja; y el crecimiento pasado no garantiza capacidad futura de reinversión.",
    investors: ["buffett"],
    source: BERKSHIRE_1989,
  },
  {
    slug: "spin-off",
    title: "Spin-off (escisión)",
    summary: "Una filial que se independiza repartiendo acciones a los accionistas.",
    body: "En un spin-off, una empresa separa una división como compañía independiente y reparte sus acciones entre los accionistas existentes, normalmente sin que paguen por ellas. El motivo declarado suele ser dar foco a cada negocio y que el mercado los valore por separado. Crea o destruye valor según la calidad de lo escindido, la deuda que se le cargue y las condiciones de la operación.",
    application:
      "Cuando una empresa de tu cartera anuncia un spin-off, lee el folleto: qué negocio se va, con cuánta deuda y con qué equipo.",
    risk: "Recibir acciones no es un regalo: el precio de la matriz se ajusta, y algunas escisiones sirven para descargar deuda o problemas.",
    investors: [],
    source: {
      title: "Wikipedia · Corporate spin-off",
      url: "https://en.wikipedia.org/wiki/Corporate_spin-off",
    },
  },
  {
    slug: "asignacion-de-capital",
    title: "Asignación de capital",
    summary: "Qué hace la empresa con la caja que genera.",
    body: "La asignación de capital es la decisión entre reinvertir, reducir deuda, repartir dividendos, recomprar acciones o comprar otras empresas. Acumulada durante años, explica gran parte de la rentabilidad del accionista. Se juzga comparando la rentabilidad de cada euro destinado con sus alternativas, no por el tamaño ni el ruido de las operaciones.",
    application:
      "Evalúa al equipo directivo por su historial de asignación de capital: es su trabajo principal una vez el negocio funciona.",
    risk: "Una sola adquisición grande y cara puede destruir años de buen negocio; el ego del comprador no aparece en las cuentas hasta después.",
    investors: [],
    source: {
      title: "Investopedia · Capital allocation",
      url: "https://www.investopedia.com/terms/c/capital_allocation.asp",
    },
  },
  {
    slug: "poder-de-precios",
    title: "Poder de precios",
    summary: "Subir precios sin perder clientes: la prueba de fuego del foso.",
    body: "El poder de precios es la capacidad de subir precios sin perder un volumen de clientes que compense la subida. Es la señal más directa de ventaja competitiva y la mejor protección contra la inflación de costes: quien lo tiene traslada el encarecimiento y conserva márgenes. Se comprueba en el historial de subidas y su efecto en ventas, no en lo que la empresa afirma.",
    application:
      "Revisa si la empresa ha subido precios en años de inflación de costes y qué pasó con sus volúmenes y márgenes.",
    risk: "El poder de precios tiene límite: abusar de él atrae competencia, reguladores o sustitutos.",
    investors: [],
    source: {
      title: "Wikipedia · Market power",
      url: "https://en.wikipedia.org/wiki/Market_power",
    },
  },
  {
    slug: "segundas-derivadas",
    title: "Segundas derivadas (efectos de segundo orden)",
    summary: "Las consecuencias de las consecuencias.",
    body: "Pensar en segundas derivadas es preguntarse qué provocan las primeras consecuencias de un acontecimiento. Una subida de tipos encarece la deuda; de segundo orden, reduce recompras, presiona el sector inmobiliario y cambia el gasto público. El mercado suele descontar la primera derivada con rapidez; la ventaja analítica está en mapear las siguientes sin inventar certezas sobre su magnitud.",
    application:
      "Ante una noticia, escribe la cadena: primera derivada, y luego qué cambia eso en los negocios que sigues.",
    risk: "Las cadenas de segundo orden se multiplican en hipótesis; cada eslabón añade incertidumbre, no certeza.",
    investors: [],
    source: {
      title: "Farnam Street · Second-order thinking",
      url: "https://fs.blog/second-order-thinking/",
    },
  },
  {
    slug: "efecto-ricardo",
    title: "Efecto Ricardo",
    summary:
      "Cómo los salarios reales cambian la intensidad de capital de la producción (escuela austríaca).",
    body: "En la teoría austríaca del ciclo, formalizada por Hayek, el efecto Ricardo describe cómo un cambio en los salarios reales altera la intensidad de capital que eligen las empresas: salarios reales más bajos hacen rentables métodos menos intensivos en capital, y al revés. Se usa para explicar cómo una expansión alimentada por crédito barato acaba mostrando desajustes entre las etapas de producción. Es un término de una escuela económica concreta, no de uso general.",
    application:
      "Sirve como marco cualitativo para entender por qué los tipos artificialmente bajos distorsionan la estructura productiva.",
    risk: "Es discutido: fuera de la escuela austríaca su validez empírica se cuestiona; no es una herramienta de valoración.",
    investors: [],
    source: {
      title: "Mises Wiki · Ricardo effect",
      url: "https://wiki.mises.org/wiki/Ricardo_effect.html",
    },
  },
];

export function conceptsForInvestor(slug: string) {
  return CONCEPTS.filter((concept) => concept.investors.includes(slug));
}
