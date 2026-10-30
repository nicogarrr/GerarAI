"""Reviewed local glossary. No model output, provider call or private context."""
from __future__ import annotations

import re
import unicodedata

# Public definitions, not current market data or personalized recommendations.
DEFINITIONS: dict[str, str] = {
    "PER": "El PER relaciona el precio de una acción con el beneficio por acción: PER = precio por acción / beneficio por acción. Indica cuánto precio corresponde a cada unidad de beneficio. Con beneficios negativos o muy pequeños pierde utilidad. No incorpora por sí solo deuda, crecimiento ni calidad del beneficio; un PER bajo no demuestra que una acción esté barata.",
    "EBITDA": "El EBITDA es el resultado antes de intereses, impuestos, depreciaciones y amortizaciones. Ayuda a comparar resultados operativos, pero no equivale al flujo de caja: no descuenta inversiones, cambios en el capital circulante ni pagos de deuda. Los ajustes del EBITDA ajustado pueden variar entre empresas y deben comprobarse en su definición.",
    "ETF": "Un ETF es un fondo cuyas participaciones cotizan en bolsa. Puede seguir un índice o una estrategia propia. Su exposición depende de lo que contiene, no de la etiqueta ETF. Tiene costes y riesgos; algunos usan derivados o apalancamiento. El precio de negociación puede diferir de su valor liquidativo.",
    "dividendo": "Un dividendo es una distribución a los accionistas, normalmente en efectivo, acordada por la empresa. No está garantizado y puede reducirse o suspenderse. La rentabilidad por dividendo relaciona el dividendo por acción con su precio, pero no mide por sí sola la rentabilidad total ni la sostenibilidad de los pagos.",
    "deuda": "La deuda es financiación que debe devolverse según unas condiciones, habitualmente con intereses. Para entenderla importan importe, vencimientos, tipo de interés, garantías y capacidad de generar caja. La deuda bruta no descuenta el efectivo; la deuda neta sí lo hace según la definición utilizada. No todo pasivo contable es deuda financiera.",
    "ingresos": "Los ingresos son los importes reconocidos por la actividad de una empresa durante un periodo según sus normas contables. No son beneficio: todavía deben descontarse costes y otros gastos. Tampoco equivalen necesariamente a cobros, porque el reconocimiento del ingreso y la entrada de efectivo pueden ocurrir en momentos distintos.",
    "beneficio": "El beneficio es el resultado de restar los gastos a los ingresos del periodo según el nivel considerado. Beneficio bruto, operativo y neto descuentan partidas diferentes. Un beneficio contable no equivale necesariamente a efectivo disponible y puede incluir partidas extraordinarias o sin movimiento de caja.",
    "margen": "Un margen expresa un resultado como proporción de los ingresos: margen = resultado / ingresos. El margen bruto, operativo y neto usan resultados distintos. Compararlo exige mantener la misma definición, periodo y actividad. Un margen alto por sí solo no demuestra crecimiento, rentabilidad sobre el capital ni generación de caja.",
    "inflación": "La inflación es el aumento del nivel general de precios durante un periodo, medido mediante un índice de una cesta de bienes y servicios. Reduce el poder adquisitivo del dinero cuando los ingresos no aumentan al mismo ritmo. El índice agregado puede diferir de la experiencia de una persona. Desinflación significa que los precios crecen más despacio, no necesariamente que bajen.",
    "interés compuesto": "El interés compuesto acumula rendimientos sobre el capital inicial y sobre rendimientos anteriores que permanecen invertidos. Con una tasa constante por periodo, el capital final es capital inicial multiplicado por (1 + tasa) elevado al número de periodos. Es un modelo simplificado: tasas variables, costes, impuestos y pérdidas cambian el resultado real.",
    "diversificación": "La diversificación reparte exposición entre activos, emisores o factores de riesgo distintos. Puede reducir el riesgo concentrado, pero no elimina las pérdidas ni todos los riesgos del mercado. Tener muchos activos no basta si responden de forma parecida. Sus correlaciones pueden cambiar, especialmente durante periodos de tensión.",
    "precio de mercado": "El precio de mercado es el precio al que un activo se negocia en un momento dado. Depende de las órdenes y condiciones del mercado. No es necesariamente su valor económico estimado ni el importe al que podría negociarse una posición grande. Liquidez, diferencial entre oferta y demanda y momento de ejecución influyen.",
    "capitalización bursátil": "La capitalización bursátil es el precio por acción multiplicado por las acciones en circulación. Mide el valor de mercado del capital de los accionistas, no el valor de toda la empresa incluyendo deuda. Puede cambiar por el precio y por emisiones o recompras de acciones. La cifra depende del momento y del recuento usado.",
    "BPA": "El beneficio por acción (BPA) divide el beneficio atribuible a los accionistas ordinarios entre el número medio ponderado de acciones del periodo. El BPA diluido incorpora instrumentos potencialmente dilutivos cuando procede. No equivale a efectivo por acción. Recompras, emisiones y partidas extraordinarias pueden afectar a su evolución.",
    "flujo de caja libre": "El flujo de caja libre suele calcularse como flujo de caja operativo menos inversiones de capital, aunque no tiene una única definición universal. Conviene distinguir el flujo disponible para toda la empresa del disponible para accionistas. Puede diferir mucho del beneficio contable por inversiones, capital circulante y partidas sin salida de efectivo.",
    "ROE": "El ROE relaciona el beneficio neto atribuible a los accionistas con sus fondos propios, a menudo medios del periodo. Mide rentabilidad contable sobre ese capital. La deuda, las recompras y unos fondos propios reducidos pueden elevarlo sin mejorar el negocio. Con patrimonio negativo su interpretación es especialmente problemática.",
    "ROIC": "El ROIC relaciona el resultado operativo después de impuestos con el capital invertido en la actividad. Busca medir la rentabilidad del capital empleado. Su cálculo varía según los ajustes del resultado y la definición de capital invertido, por lo que las comparaciones exigen criterios consistentes.",
    "valor de empresa": "El valor de empresa suele partir de la capitalización bursátil, añadir deuda financiera y otras reclamaciones sobre el negocio y restar efectivo. Los ajustes por arrendamientos, minoritarios y otros activos pueden variar. No es lo mismo que el valor de mercado de las acciones ni una valoración intrínseca demostrada.",
    "balance": "El balance muestra activos, pasivos y patrimonio neto en una fecha. Su identidad básica es activo = pasivo + patrimonio neto. Es una fotografía contable, no una medida directa del valor de mercado ni un registro de todos los cobros y pagos. Las notas explican criterios y partidas que el resumen puede ocultar.",
    "flujo de caja": "El flujo de caja describe entradas y salidas de efectivo durante un periodo. El estado de flujos las agrupa en actividades operativas, de inversión y de financiación. Una entrada de efectivo puede proceder de nueva deuda y no de beneficios; por eso el cambio total de caja no mide por sí solo el desempeño del negocio.",
    "bono": "Un bono es un instrumento de deuda con condiciones de intereses y devolución. Su precio puede variar por tipos de interés, riesgo de crédito y liquidez. Cupón y rentabilidad no son lo mismo: la rentabilidad depende también del precio y de los pagos que finalmente se reciban. Mantenerlo hasta vencimiento no elimina el riesgo de impago.",
    "acción": "Una acción representa una participación en el capital de una empresa, con derechos que dependen de su clase y de las normas aplicables. Su precio y sus dividendos pueden variar. En una liquidación los accionistas cobran después de los acreedores, por lo que pueden perder toda su aportación.",
    "índice bursátil": "Un índice bursátil resume la evolución de una cesta de valores mediante unas reglas de selección y ponderación. No todos ponderan por capitalización ni reinvierten dividendos. Un índice de precios y otro de rentabilidad total pueden mostrar resultados distintos. El índice es una medida; los productos que lo siguen tienen costes y posibles diferencias de seguimiento.",
    "tipo de interés": "El tipo de interés expresa el coste o rendimiento del dinero por periodo respecto al capital. Para compararlo importan periodicidad, capitalización y comisiones. El tipo nominal no siempre coincide con la tasa anual efectiva. El tipo real considera el efecto de la inflación, con resultados distintos según la medida utilizada.",
    "deuda neta": "La deuda neta suele ser deuda financiera menos efectivo y equivalentes disponibles. No existe una definición única: pueden variar el tratamiento de arrendamientos, inversiones líquidas y efectivo restringido. Una cifra negativa indica más caja que la deuda incluida en ese cálculo, pero no prueba por sí sola ausencia de otros compromisos.",
    "activo": "Un activo contable es un recurso económico controlado por una entidad como resultado de hechos pasados. Puede ser efectivo, una cuenta a cobrar, un inmueble o un derecho intangible, entre otros. Su importe contable no tiene por qué coincidir con su valor de mercado ni con el efectivo recuperable.",
    "pasivo": "Un pasivo es una obligación presente de transferir un recurso económico derivada de hechos pasados. Incluye, entre otras partidas, deudas, cuentas a pagar y determinadas provisiones. No todos los pasivos tienen intereses ni el mismo plazo. Importe, vencimientos y condiciones ayudan a interpretar la obligación.",
    "patrimonio neto": "El patrimonio neto es la diferencia contable entre activos y pasivos. Incluye aportaciones de los propietarios y resultados acumulados, entre otras partidas. No equivale a capitalización bursátil ni al importe que recibirían necesariamente los accionistas si se liquidara la empresa.",
    "amortización": "En contabilidad, la amortización distribuye el coste de ciertos activos a lo largo de su vida útil; según el contexto puede distinguirse de la depreciación de activos materiales. No representa necesariamente una salida de caja en ese periodo. En deuda, amortizar significa devolver principal, que es un uso distinto del término.",
    "rentabilidad": "La rentabilidad relaciona el resultado obtenido con el capital o precio inicial durante un periodo. En un activo, la rentabilidad total incluye cambios de precio y distribuciones recibidas, con ajustes cuando procede. Compararla exige el mismo plazo y criterio de costes e impuestos. Una rentabilidad pasada no garantiza resultados futuros.",
    "volatilidad": "La volatilidad mide la variación de una serie de rendimientos durante un periodo y suele expresarse con una desviación típica. Depende de la frecuencia y ventana elegidas. Describe fluctuaciones, no todas las formas de riesgo: no mide por sí sola impago, liquidez o pérdida permanente.",
    "liquidez": "La liquidez puede referirse a la capacidad de negociar un activo con rapidez y sin alterar mucho su precio, o a la capacidad de una entidad para afrontar pagos próximos. Son sentidos distintos. Un activo cotizado no siempre es líquido y una empresa rentable puede tener dificultades de caja.",
    "apalancamiento": "El apalancamiento amplía una exposición mediante deuda, derivados u otros compromisos. Puede aumentar tanto ganancias como pérdidas respecto al capital propio. Sus riesgos dependen de garantías, vencimientos y condiciones de financiación. No se limita a la deuda que aparece de forma evidente en el balance.",
    "dilución": "La dilución es la reducción de la participación relativa o de ciertas magnitudes por acción al aumentar las acciones o los derechos que pueden convertirse en ellas. Su efecto económico depende del precio y del uso de los recursos obtenidos. No toda emisión destruye valor, aunque sí puede cambiar el reparto de propiedad.",
    "valor contable": "El valor contable es el importe registrado de un activo, pasivo o patrimonio según las normas contables. Para acciones suele usarse el patrimonio atribuible por acción. No es una estimación automática del valor de mercado o de liquidación. Activos no reconocidos, deterioros y criterios contables pueden afectar a la comparación.",
    # Tanda 2026-10-20 (apuntes manuscritos de Nico): mismas reglas - definiciones
    # revisadas, sin LLM, sin datos de mercado ni recomendaciones.
    "WACC": "El WACC (coste medio ponderado de capital) es el coste de financiar una empresa ponderando el coste de los fondos propios y el de la deuda según su peso en la financiación. Se usa como tasa de descuento y como referencia para el ROIC: si la rentabilidad del capital invertido no supera el WACC, la empresa no crea valor. Su cálculo depende de hipótesis como la beta o la prima de riesgo; dos analistas pueden obtener WACC distintos y defendibles.",
    "CFROI": "El CFROI (cash flow return on investment) estima la rentabilidad de la inversión a partir de sus flujos de caja. Su formulación completa usa una tasa interna de rentabilidad sobre la inversión bruta, con ajustes por inflación y vida útil de los activos. No es simplemente flujo de caja dividido por activos. Las aproximaciones deben declarar fórmula y límites antes de compararse con el coste de capital.",
    "foso competitivo": "Un foso competitivo (moat) es una ventaja que protege los beneficios de una empresa frente a la competencia durante años: marca, costes menores, costes de cambio, efectos de red o barreras regulatorias, entre otras. El término lo popularizó Buffett. No toda ventaja dura: conviene preguntarse qué la sostiene y si seguirá existiendo dentro de diez años. Un foso sin buen precio de compra no garantiza una buena inversión.",
    "beneficio del propietario": "El beneficio del propietario (owner earnings), descrito por Buffett en 1986, parte del beneficio contable, suma depreciación, amortización y ciertos cargos sin salida de caja, y resta la inversión media necesaria para mantener la posición competitiva y el volumen del negocio, incluidas las necesidades adicionales de capital circulante. La inversión de mantenimiento exige juicio y no siempre se publica por separado. No equivale automáticamente al FCF ni a beneficio neto más D&A menos capex total.",
    "capex de mantenimiento y de crecimiento": "El capex de mantenimiento busca conservar la capacidad y la posición competitiva actuales; el de crecimiento busca ampliarlas. Ambos suponen salidas de caja y pueden capitalizarse contablemente. Separarlos ayuda a estimar la caja que generaría el negocio sin expansión, pero no hay una regla universal: muchas empresas no publican el desglose. D&A puede servir de aproximación, no prueba cuánto mantenimiento necesita el negocio.",
    "trampa de valor": "Una trampa de valor es una acción que parece barata por sus múltiplos pero cuyo negocio se deteriora de forma permanente: beneficios que caen, ventaja competitiva perdida o deuda excesiva. El precio bajo descuenta un empeoramiento real, no una oportunidad. Para distinguirla de una ganga hay que comprobar si la generación de caja y la posición competitiva se mantienen. Que una acción haya caído mucho no es evidencia de que esté barata.",
    "ciclo económico": "El ciclo económico es la alternancia de fases de expansión y contracción de la actividad, el empleo y los beneficios. No tiene duración fija ni se puede predecir con precisión. Afecta de forma distinta a cada sector: las empresas cíclicas amplifican el ciclo y las defensivas lo atenúan. Valorar una cíclica con los beneficios del mejor momento del ciclo sobreestima su capacidad normal de generar caja.",
    "curva de tipos": "La curva de tipos relaciona rendimientos y vencimientos de instrumentos de deuda comparables en una fecha. Para deuda pública suele usarse un mismo emisor o una curva de referencia homogénea. Puede tener pendiente positiva, plana o invertida. Refleja expectativas de tipos futuros y primas por plazo y riesgo. Una inversión de la curva no es un calendario seguro de recesión.",
    "deflación": "La deflación es el descenso sostenido del nivel general de precios, distinto de la desinflación, que es una menor tasa de subida. Puede deberse a una demanda débil o a mejoras de oferta y productividad; sus efectos dependen de la causa. Puede aumentar el peso real de deudas nominales y, cuando se espera que continúe, aplazar parte del gasto. Una bajada aislada de un producto no demuestra deflación.",
    "banco central": "Un banco central es la institución pública que emite la moneda, fija los tipos de interés oficiales y vela por la estabilidad de precios y del sistema financiero; en la zona euro es el BCE y en Estados Unidos la Reserva Federal. Sus decisiones de tipos afectan al coste de la deuda, a la valoración de los activos y a la inflación. Su independencia formal no elimina el debate sobre sus criterios y errores.",
    "compounder": "Un compounder (componedor) es una empresa capaz de reinvertir sus beneficios a rentabilidades altas durante muchos años, de modo que su valor crece de forma compuesta. La clave no es solo que crezca, sino que cada euro retenido rinda por encima de su coste de capital. Son negocios poco frecuentes; el riesgo es pagar de más por ellos o confundir crecimiento pasado con capacidad futura.",
    "spin-off": "Un spin-off es la separación de una división o filial como empresa independiente, repartiendo sus acciones entre los accionistas existentes, normalmente sin que paguen por ellas. El motivo declarado suele ser dar foco a cada negocio. Puede crear o destruir valor según la calidad de lo escindido, la deuda que se le cargue y las condiciones de la operación. Recibir acciones de un spin-off no es un ingreso gratuito: el precio de la empresa matriz se ajusta.",
    "asignación de capital": "La asignación de capital es la decisión de qué hacer con la caja que genera una empresa: reinvertir, reducir deuda, repartir dividendos, recomprar acciones o comprar otras empresas. A largo plazo es una de las decisiones que más explican la rentabilidad para el accionista. Se juzga comparando la rentabilidad de cada euro destinado con sus alternativas, no por el tamaño de las operaciones. Una adquisición cara puede destruir años de buen negocio.",
    "poder de precios": "El poder de precios es la capacidad de una empresa de aumentar sus precios sin perder suficiente demanda como para perjudicar la rentabilidad. Puede apoyarse en diferenciación, costes de cambio u otras barreras y no es ilimitado. Conviene comprobar precios, volúmenes, competencia y márgenes conjuntamente. Trasladar una subida de costes a clientes puede mostrarlo, pero una subida de precios por sí sola no lo demuestra.",
    "segundas derivadas": "Pensar en segundas derivadas (efectos de segundo orden) es preguntarse no solo qué provoca un acontecimiento, sino qué provocan esas primeras consecuencias. Una subida de tipos encarece la deuda; de segundo orden, puede reducir recompras, presionar el sector inmobiliario o cambiar el gasto público. El mercado suele descontar la primera derivada rápido; la ventaja analítica está en mapear las siguientes sin inventar certezas sobre su magnitud.",
    "efecto Ricardo": "El efecto Ricardo relaciona el coste relativo del trabajo y del capital con la elección entre métodos más intensivos en trabajo o en maquinaria: si el trabajo se encarece relativamente, puede convenir sustituirlo por capital, y a la inversa. La interpretación del mecanismo dentro de la teoría austríaca del ciclo es discutida. No debe confundirse con la equivalencia ricardiana sobre impuestos y deuda pública.",
}


def _normalize(text: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip()


_ALIASES = {_normalize(k): k for k in DEFINITIONS}
_ALIASES.update({
    "dividendos": "dividendo", "revenue": "ingresos", "beneficios": "beneficio",
    "margenes": "margen", "eps": "BPA", "beneficio por accion": "BPA",
    "fcf": "flujo de caja libre", "cash flow": "flujo de caja", "cash flow libre": "flujo de caja libre",
    "enterprise value": "valor de empresa", "equity": "patrimonio neto", "acciones": "acción",
    "bonos": "bono", "etfs": "ETF", "depreciacion": "amortización",
    # Tanda 2026-10-20
    "moat": "foso competitivo", "moats": "foso competitivo", "fosos": "foso competitivo",
    "owner earnings": "beneficio del propietario",
    "capex": "capex de mantenimiento y de crecimiento",
    "capex de mantenimiento": "capex de mantenimiento y de crecimiento",
    "capex de crecimiento": "capex de mantenimiento y de crecimiento",
    "value trap": "trampa de valor", "trampas de valor": "trampa de valor",
    "ciclos economicos": "ciclo económico",
    "curva de rendimientos": "curva de tipos", "yield curve": "curva de tipos",
    "curva invertida": "curva de tipos",
    "bancos centrales": "banco central", "componedor": "compounder",
    "spin off": "spin-off", "spin offs": "spin-off", "spinoffs": "spin-off",
    "capital allocation": "asignación de capital", "pricing power": "poder de precios",
    "efectos de segundo orden": "segundas derivadas",
    "second order thinking": "segundas derivadas",
})
_PREFIX = r"(?:que es|que son|que significa|como funciona|como se calcula|explica|explicame|define|what is|how does) "


def canonical_concept(question: str) -> str | None:
    # Only exact public-concept questions. Extra text stays on the original route.
    value = re.sub(r"^[¿¡\s]+|[?!.\s]+$", "", _normalize(question))
    match = re.fullmatch(_PREFIX + r"(?:(?:el|la|los|las|un|una|the|an|a) )?(.+?)(?: work)?", value)
    return _ALIASES.get(match.group(1)) if match else None


def local_definition(question: str) -> str | None:
    concept = canonical_concept(question)
    return DEFINITIONS.get(concept) if concept else None


_FOLLOWUP_RE = re.compile(r"(?:y|entonces) (?:(?:el|la|los|las|un|una|the) )?(.+?)")


def followup_definition(question: str, last_user_question: str | None) -> str | None:
    """«¿qué es el PER?» → «¿y el FCF?»: la forma abreviada solo vale si el
    turno anterior del usuario ya era una pregunta de concepto. Sin ese ancla,
    «¿y el efectivo?» en otro contexto no es una consulta de glosario.
    """
    if canonical_concept(last_user_question or "") is None:
        return None
    value = re.sub(r"^[¿¡\s]+|[?!.\s]+$", "", _normalize(question))
    match = re.fullmatch(_FOLLOWUP_RE, value)
    if not match:
        return None
    return DEFINITIONS.get(_ALIASES.get(match.group(1)) or "")
