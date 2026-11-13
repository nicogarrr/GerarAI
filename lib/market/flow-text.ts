/**
 * Flujos de dinero de Temas (money_flows.py y energy_flows.py): el backend
 * manda en castellano el nombre del flujo, las razones de cada gastador y
 * proveedor, las etiquetas de destino, las notas, el método y la limitación.
 * En inglés se traducen; en castellano, y con un texto que no se reconoce,
 * pasa el del backend tal cual (importes, fuentes y enlaces no se tocan).
 */
import { naFor } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import type { FlowSource, MoneyFlow } from '@/lib/market/flows';
// Textos nuevos del backend que ya no caben en el mapa de abajo (el guard de
// i18n tiene este fichero en su techo): viven en los diccionarios y aquí solo
// se cruzan. Import relativo con atributo por los tests con node
// --experimental-strip-types.
import esThemes from '../i18n/messages/es/themes.json' with { type: 'json' };
import enThemes from '../i18n/messages/en/themes.json' with { type: 'json' };

// Uso por literal para el guard de i18n (claves consumidas por objeto).
export const FLOW_BACKEND_TEXT_KEY_LITERALS = ['themes.flow.backendText.leaseCurrencyMismatch'] as const;
const FLOW_DICT_EN: Record<string, string> = {
  [esThemes.flow.backendText.leaseCurrencyMismatch]: enThemes.flow.backendText.leaseCurrencyMismatch,
};

const FLOW_EN: Record<string, string> = {
  // Temas
  'Electricidad de EE. UU.': 'US electricity',
  'Gasto eléctrico por sector y quién lo recibe, sin repartirlo entre empresas': 'Electricity spending by sector and who receives it, not split across companies',
  'EIA API v2, retail-sales: ingresos anuales reportados, US Total, millones de dólares convertidos a USD':
    'EIA API v2, retail-sales: reported annual revenue, US Total, million dollars converted to USD',
  'Solo electricidad al por menor en EE. UU., no todo el sector energético ni capex. Gasto del cliente e ingreso del vendedor son el mismo flujo: no se suman. Sin reparto verificable por empresa ni exposición cuantificada de cartera. Datos revisables.':
    'US retail electricity only, not the whole energy sector or capex. Customer spending and seller revenue are the same flow: they are not added together. No verifiable split by company and no quantified portfolio exposure. Data subject to revision.',
  'Capex de IA': 'AI capex',
  'Quién financia la buildout de IA y quién cobra de ella': 'Who funds the AI buildout and who gets paid from it',
  'Capex trimestral reportado (SEC/ESEF, enlazado a su filing) + reparto estimado por Morgan Stanley Research 2027E, citado con atribución':
    'Reported quarterly capex (SEC/ESEF, linked to its filing) + split estimated by Morgan Stanley Research 2027E, cited with attribution',
  "El reparto por categorías es estimación de analistas: su propia fuente suma 1.583 B$ contra destinos por 1.734 B$ (+151 B$ sin explicar) y excluye 136 B$ de memoria HBM. No hay fuente gratuita del reparto por proveedor: las empresas de 'quién cobra' van con su razón declarada, sin importe.":
    "The split by category is an analyst estimate: its own source adds up to $1,583B against $1,734B of destinations (+$151B unexplained) and excludes $136B of HBM memory. There is no free source for the split by supplier: the 'who gets paid' companies are listed with their stated reason, without an amount.",
  'Defensa de EE. UU.': 'US defense',
  'Del presupuesto federal a los contratistas': 'From the federal budget to the contractors',
  'Obligaciones de contratos y ayudas de USAspending.gov (API oficial), último año fiscal completo':
    'Contract and grant obligations from USAspending.gov (official API), last complete fiscal year',
  "USAspending no incluye personal ni operaciones internas del DoD (solo 'awards'), y los contratos del DoD se publican con 90 días de retraso declarado. Obligado no es desembolsado. El mapeo de recipiente a ticker es curado y declarado empresa a empresa.":
    "USAspending does not include DoD personnel or internal operations (only 'awards'), and DoD contracts are published with a stated 90-day delay. Obligated is not disbursed. The recipient-to-ticker mapping is curated and stated company by company.",
  // Gastadores
  'Departamento de Defensa de EE. UU.': 'US Department of Defense',
  'Mayor agencia federal por obligaciones de contratos y ayudas.': 'Largest federal agency by contract and grant obligations.',
  'Reporta su capex trimestral en el 10-Q (infraestructura técnica: servidores y centros de datos).':
    'Reports its quarterly capex in the 10-Q (technical infrastructure: servers and data centers).',
  'Reporta su capex trimestral en el 10-Q; la guía de la empresa lo vincula a la demanda de Azure e IA.':
    "Reports its quarterly capex in the 10-Q; the company's guidance ties it to Azure and AI demand.",
  "Reporta el capex como 'productive assets' en el 10-Q, mayoritariamente AWS.": "Reports capex as 'productive assets' in the 10-Q, mostly AWS.",
  'Reporta su capex trimestral en el 10-Q y da guía anual ligada a IA en sus presentaciones de resultados.':
    'Reports its quarterly capex in the 10-Q and gives annual AI-linked guidance in its earnings presentations.',
  'Reporta su capex trimestral en el 10-Q; su backlog (RPO) lo vincula a contratos de nube e IA.':
    'Reports its quarterly capex in the 10-Q; its backlog (RPO) ties it to cloud and AI contracts.',
  'Neocloud cotizada: reporta su capex en el 10-Q; su negocio es alquilar GPUs a terceros.': 'Listed neocloud: reports its capex in the 10-Q; its business is renting GPUs to others.',
  'Neocloud cotizada: reporta su capex en sus filings (20-F/6-K); negocio de infraestructura de IA.':
    'Listed neocloud: reports its capex in its filings (20-F/6-K); AI infrastructure business.',
  'Gasto de los clientes en electricidad al por menor, medido por ingresos de ventas.': 'Customer spending on retail electricity, measured by sales revenue.',
  Hogares: 'Households',
  'Comercios y servicios': 'Commerce and services',
  Industria: 'Industry',
  Transporte: 'Transportation',
  Otros: 'Other',
  // Destinos
  'Chips de IA y servidores': 'AI chips and servers',
  'Memoria (HBM y otra)': 'Memory (HBM and other)',
  'Red y óptica': 'Networking and optics',
  'Infraestructura de centros de datos y energía': 'Data center infrastructure and power',
  'Aviones de ala fija': 'Fixed-wing aircraft',
  'Buques de guerra': 'Warships',
  'Misiles guiados': 'Guided missiles',
  'Motores de aviación militar': 'Military aircraft engines',
  'Servicios de ingeniería y soporte técnico': 'Engineering and technical support services',
  'Otros servicios profesionales': 'Other professional services',
  'Sanidad militar (TRICARE)': 'Military healthcare (TRICARE)',
  'I+D de defensa (desarrollo experimental)': 'Defense R&D (experimental development)',
  'Componentes de aeronaves': 'Aircraft components',
  'Mantenimiento de aeronaves': 'Aircraft maintenance',
  'Compra de electricidad al por menor': 'Retail electricity purchases',
  // Proveedores
  'Sus GPUs y el ecosistema CUDA son el acelerador dominante en los centros de datos de IA.': 'Its GPUs and the CUDA ecosystem are the dominant accelerator in AI data centers.',
  'Diseña chips de red (Tomahawk/Jericho) y aceleradores a medida (XPU) para hyperscalers.': 'Designs networking chips (Tomahawk/Jericho) and custom accelerators (XPU) for hyperscalers.',
  'Chips a medida e interconexión óptica (DSP) para centros de datos de IA.': 'Custom chips and optical interconnect (DSP) for AI data centers.',
  'Switches Ethernet de centros de datos; sus mayores clientes son hyperscalers.': 'Data center Ethernet switches; its largest customers are hyperscalers.',
  'Refrigeración y distribución eléctrica de centros de datos.': 'Data center cooling and power distribution.',
  'Equipos eléctricos de media tensión y distribución para centros de datos.': 'Medium-voltage electrical and distribution equipment for data centers.',
  'Único fabricante estadounidense de memoria; vende HBM para aceleradores de IA.': 'The only US memory maker; sells HBM for AI accelerators.',
  'Fabrica (foundry) la mayoría de los chips avanzados de IA diseñados por terceros.': 'Manufactures (foundry) most advanced AI chips designed by others.',
  'Monopolio de la litografía EUV necesaria para fabricar chips avanzados.': 'Monopoly on the EUV lithography needed to make advanced chips.',
  'Servidores con GPUs para IA; monta racks para empresas y neoclouds.': 'GPU servers for AI; builds racks for enterprises and neoclouds.',
  'Servidores y racks con GPUs, gran parte ligada a NVIDIA.': 'GPU servers and racks, largely tied to NVIDIA.',
  'Herramientas EDA: software necesario para diseñar chips.': 'EDA tools: software needed to design chips.',
  'Filial de Lockheed Martin (helicópteros).': 'Lockheed Martin subsidiary (helicopters).',
  'Mayor contratista de defensa de EE. UU. por obligaciones.': 'Largest US defense contractor by obligations.',
  'Filial de General Dynamics (submarinos).': 'General Dynamics subsidiary (submarines).',
  'Contratista de defensa (Gulfstream, combat systems, GDIT).': 'Defense contractor (Gulfstream, combat systems, GDIT).',
  'Filial de RTX (misiles y defensa aérea).': 'RTX subsidiary (missiles and air defense).',
  'Matriz de Raytheon, Collins y Pratt & Whitney.': 'Parent of Raytheon, Collins and Pratt & Whitney.',
  'Defensa (cazas, misiles, espacio) dentro de Boeing.': 'Defense (fighters, missiles, space) within Boeing.',
  'Contratista de defensa (bombarderos, espacio, misiles).': 'Defense contractor (bombers, space, missiles).',
  'Astilleros militares (portaaviones y destructores).': 'Military shipyards (aircraft carriers and destroyers).',
  'Electrónica de defensa y comunicaciones.': 'Defense electronics and communications.',
  'GE Aerospace: motores de aviación militar.': 'GE Aerospace: military aircraft engines.',
  'Servicios de defensa e inteligencia.': 'Defense and intelligence services.',
  'Filial de Cencora: distribución farmacéutica al sistema sanitario militar.': 'Cencora subsidiary: pharmaceutical distribution to the military health system.',
  'Gestiona parte del seguro sanitario militar (TRICARE).': 'Manages part of the military health insurance (TRICARE).',
  'Gestora de TRICARE; empresa privada, sin ticker.': 'TRICARE manager; private company, no ticker.',
  'Contratista británica (BA. en Londres), fuera del universo US.': 'British contractor (BA. in London), outside the US universe.',
  'Drones MQ-9; empresa privada, sin ticker.': 'MQ-9 drones; private company, no ticker.',
  'Distribución farmacéutica al sistema sanitario militar.': 'Pharmaceutical distribution to the military health system.',
  'Suministros; empresa privada, sin ticker.': 'Supplies; private company, no ticker.',
  'Sin mapeo a ticker declarado': 'No stated ticker mapping',
  'Contratista según USAspending': 'Contractor according to USAspending',
  'Vendedores de electricidad en EE. UU. (agregado)': 'US electricity sellers (aggregate)',
  'Mismo ingreso que el gasto mostrado arriba; no es un flujo adicional.': 'The same revenue as the spending shown above; it is not an additional flow.',
  // Notas
  'Filing referenciado por accession; sin enlace directo guardado': 'Filing referenced by accession; no direct link stored',
  'Sin datos SEC en la app todavía': 'No SEC data in the app yet',
  'Sin capex trimestral reportado en los datos de la app': 'No reported quarterly capex in the app data',
  'Leases financieros nuevos (mismo periodo)': 'New finance leases (same period)',
  'Obligaciones de contratos y ayudas; no incluye personal ni operaciones internas': 'Contract and grant obligations; excludes personnel and internal operations',
  'Etiqueta oficial de la fuente, en inglés': "The source's official label, in English",
  'USAspending no disponible ahora mismo': 'USAspending unavailable right now',
  'Estimación de analistas; no verificable con fuentes gratuitas': 'Analyst estimate; not verifiable with free sources',
  'Sin reparto público verificable: no hay fuente gratuita de cuánto le compra cada gastador':
    'No verifiable public split: there is no free source for how much each spender buys from it',
  'Sin importes: no hay fuente gratuita del reparto por proveedor': 'No amounts: there is no free source for the split by supplier',
  'EIA no configurada o no disponible: gasto eléctrico N/D. No se estiman importes.': `EIA not configured or unavailable: electricity spending ${naFor('en')}. No amounts are estimated.`,
  'Ingresos declarados por vendedores de electricidad; datos revisables': 'Revenue reported by electricity sellers; data subject to revision',
  'Sin reparto de estos ingresos entre empresas cotizadas': 'No split of this revenue across listed companies',
  'Total agregado del mismo flujo, no ingresos atribuibles a las empresas de la cesta': 'Aggregate total of the same flow, not revenue attributable to the basket companies',
};

/** Textos con cifras o fechas: se traduce la plantilla y se conservan los valores. */
const FLOW_PATTERNS_EN: Array<[RegExp, (...groups: string[]) => string]> = [
  [/^Principales categorías: cubren el (\d+) % de lo obligado$/, (pct) => `Top categories: they cover ${pct}% of the obligated amount`],
  [/^Principales recipientes: cubren el (\d+) % de lo obligado$/, (pct) => `Top recipients: they cover ${pct}% of the obligated amount`],
  [/^Obligaciones (.+)$/, (fy) => `Obligations ${fy}`],
  [/^USAspending no disponible ahora mismo \((\w+)\); sin cifras en lugar de inventarlas$/, (err) => `USAspending unavailable right now (${err}); no figures rather than made-up ones`],
  [
    /^(\d+) de (\d+) gastadores incluidos \(solo USD reportado\); los periodos no coinciden necesariamente entre empresas$/,
    (n, total) => `${n} of ${total} spenders included (reported USD only); periods don't necessarily match across companies`,
  ],
  [/^5 de 5 sectores incluidos · EE\. UU\. (\d{4}); ALL es control, no se suma otra vez$/, (year) => `5 of 5 sectors included · US ${year}; ALL is a control total, not added again`],
  [/^USAspending\.gov · categoría PSC (\S+) · (.+)$/, (code, fy) => `USAspending.gov · PSC category ${code} · ${fy}`],
  [/^EIA · ventas eléctricas EE\. UU\. · (\d{4})$/, (year) => `EIA · US electricity sales · ${year}`],
  [/^FY(\d{4}) federal \(oct (\d{4})–sep (\d{4})\)$/, (fy, from, to) => `FY${fy} federal (Oct ${from}–Sep ${to})`],
];

export function flowText<T extends string | null | undefined>(text: T, locale: Locale): T | string {
  if (locale !== 'en' || !text) return text;
  if (Object.hasOwn(FLOW_EN, text)) return FLOW_EN[text];
  if (Object.hasOwn(FLOW_DICT_EN, text)) return FLOW_DICT_EN[text];
  for (const [pattern, render] of FLOW_PATTERNS_EN) {
    const match = pattern.exec(text);
    if (match) return render(...match.slice(1).map((group) => flowText(group, locale) as string));
  }
  return text;
}

function sourceText(source: FlowSource, locale: Locale): FlowSource {
  return { ...source, label: flowText(source.label, locale), note: flowText(source.note, locale) };
}

/** El flujo con sus textos en el idioma elegido; en castellano, el mismo objeto. */
export function localizeFlow(flow: MoneyFlow, locale: Locale): MoneyFlow {
  if (locale !== 'en') return flow;
  return {
    ...flow,
    name: flowText(flow.name, locale),
    tagline: flowText(flow.tagline, locale),
    period_label: flowText(flow.period_label, locale),
    method: flowText(flow.method, locale),
    limitation: flowText(flow.limitation, locale),
    notes: flow.notes.map((note) => flowText(note, locale)),
    destinations_note: flowText(flow.destinations_note, locale),
    suppliers_note: flowText(flow.suppliers_note, locale),
    spenders_total: flow.spenders_total ? { ...flow.spenders_total, note: flowText(flow.spenders_total.note, locale) } : null,
    spenders: flow.spenders.map((spender) => ({
      ...spender,
      label: flowText(spender.label, locale),
      period_label: flowText(spender.period_label, locale),
      reason: flowText(spender.reason, locale),
      note: flowText(spender.note, locale),
      extra_label: flowText(spender.extra_label, locale),
      source: spender.source ? sourceText(spender.source, locale) : null,
      extra_source: spender.extra_source ? sourceText(spender.extra_source, locale) : null,
    })),
    destinations: flow.destinations.map((destination) => ({
      ...destination,
      label: flowText(destination.label, locale),
      source: sourceText(destination.source, locale),
    })),
    suppliers: flow.suppliers.map((supplier) => ({
      ...supplier,
      name: flowText(supplier.name, locale),
      reason: flowText(supplier.reason, locale),
      note: flowText(supplier.note, locale),
      source: supplier.source ? sourceText(supplier.source, locale) : null,
    })),
  };
}
