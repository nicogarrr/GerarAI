/**
 * Constantes centralizadas del proyecto
 * Reemplaza magic numbers y strings hardcodeados
 */

import {
  Bell,
  BookOpen,
  Briefcase,
  Building2,
  CircleHelp,
  FileSearch,
  Filter,
  CalendarDays,
  Gauge,
  Home,
  Library,
  Lightbulb,
  FlaskConical,
  LineChart,
  Newspaper,
  Receipt,
  Share2,
  Sparkles,
  Star,
  Target,
  Landmark,
    Users,
    UsersRound,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import type { TranslationKey } from '@/lib/i18n/messages';

// Timeouts (en milisegundos)
export const TIMEOUTS = {
  API_REQUEST: 10000, // 10 segundos para requests de API
  API_REQUEST_FAST: 8000, // 8 segundos para requests rápidos
  DATABASE_CONNECTION: 30000, // 30 segundos para conexión a DB
  SERVER_SELECTION: 30000, // 30 segundos para selección de servidor MongoDB
} as const;

// Validación de símbolos
export const SYMBOL_VALIDATION = {
  MIN_LENGTH: 1,
  MAX_LENGTH: 10,
  PATTERN: /^[A-Z0-9.-]+$/, // Solo letras mayúsculas, números, puntos y guiones
} as const;

// Etiquetas en espanol, alineadas con el titulo (H1) de cada pagina.
//
// Estructura de ARBOL, no de lista plana con prefijos: `children` crea la
// indentacion real y hace que "Cartera" agrupe sus cuatro vistas en vez de
// repetir "Cartera · " en cada etiqueta. Un href solo debe aparecer una vez:
// `Sidebar`, `NavItems` y `Breadcrumbs` leen de aqui, y las paginas huerfanas
// se descubren comparando las rutas del app/ con esta lista.
export type NavItem = {
  href: string;
  /** Clave i18n de la etiqueta (messages nav.*); se resuelve con t() en el componente. */
  labelKey: TranslationKey;
  icon: LucideIcon;
  /**
   * Hub primario (una de las 6 entradas de NAV_SECTIONS) al que pertenece la
   * ruta: decide el resaltado del menu y el subnav contextual (SectionNav).
   * `null` = sin hub (destinos de apoyo como /help): no se resalta nada.
   */
  hub?: string | null;
  /** Clave i18n de la descripcion de una linea para tarjetas de hub (/discover). */
  descriptionKey?: TranslationKey;
  /**
   * Clave i18n de la etiqueta corta solo para el subnav contextual
   * (SectionNav), cuando la etiqueta del catalogo (alineada con el H1)
   * repetiria el nombre de la seccion: /research se anuncia como
   * «Empresas» dentro de Research. Migas, buscador y /discover siguen
   * usando `labelKey`.
   */
  subnavLabelKey?: TranslationKey;
  /**
   * Oculta el enlace a la propia página en el subnav contextual cuando la
   * página YA ofrece ese destino con su propia navegación: /portfolio tiene
   * la pestaña «Resumen» y /knowledge el encabezado «Conocimiento», y el
   * subnav pintaba el mismo nombre una línea encima (duplicado QA).
   */
  subnavHideSelf?: boolean;
  children?: NavItem[];
};

export type NavSection = {
  /** Clave i18n del titulo de seccion; sin clave = seccion sin titulo visible. */
  titleKey?: TranslationKey;
  items: NavItem[];
};

export const NAV_SECTIONS: NavSection[] = [{
  items: [
    { href: '/inicio', labelKey: 'nav.items.inicio', icon: Home },
    { href: '/portfolio', labelKey: 'nav.portfolio', icon: Briefcase },
    { href: '/research', labelKey: 'nav.research', icon: FileSearch },
    { href: '/discover', labelKey: 'nav.items.discover', icon: Filter },
    { href: '/watchlist', labelKey: 'nav.items.watchlist', icon: Star },
    { href: '/knowledge', labelKey: 'nav.items.knowledge', icon: BookOpen },
  ],
}];

export const ROUTE_CATALOG: NavSection[] = [
  {
    titleKey: 'nav.sections.principal',
    items: [
      { href: '/inicio', labelKey: 'nav.items.inicio', icon: Home, hub: '/inicio' },
      { href: '/discover', labelKey: 'nav.items.discover', icon: Filter, hub: '/discover' },
    ],
  },
  {
    titleKey: 'nav.sections.cartera',
    items: [
      { href: '/portfolio', labelKey: 'nav.items.resumen', icon: Briefcase, hub: '/portfolio', subnavHideSelf: true },
      { href: '/portfolio/intelligence', labelKey: 'nav.items.inteligencia', icon: Sparkles, hub: '/portfolio' },
      { href: '/risk', labelKey: 'nav.items.exposiciones', icon: Gauge, hub: '/portfolio' },
      { href: '/taxes', labelKey: 'nav.items.impuestos', icon: Receipt, hub: '/portfolio' },
      { href: '/corporate-actions', labelKey: 'nav.items.accionesCorp', icon: Building2, hub: '/portfolio' },
      { href: '/calendar', labelKey: 'nav.items.calendario', icon: CalendarDays, hub: '/portfolio' },
      { href: '/portfolio/stress', labelKey: 'nav.items.estresHistorico', icon: LineChart, hub: '/portfolio' },
      { href: '/paper-trading', labelKey: 'nav.items.cuentaDemo', icon: FlaskConical, hub: '/portfolio' },
    ],
  },
  {
    titleKey: 'nav.sections.analisis',
    items: [
      {
        href: '/research',
        labelKey: 'nav.research',
        icon: FileSearch,
        hub: '/research',
        subnavLabelKey: 'nav.items.empresas',
        children: [
          { href: '/research/news', labelKey: 'nav.items.noticias', icon: Newspaper, hub: '/research' },
          { href: '/research/sources', labelKey: 'nav.items.fuentes', icon: Library, hub: '/research' },
        ],
      },
      {
        href: '/screeners',
        labelKey: 'nav.screeners',
        icon: Filter,
        hub: '/discover',
        // Sin tarjeta propia en /discover (sin descriptionKey): duplicaba
        // concepto con «Explorar acciones» (informe UX 29-oct, punto 7). Se
        // llega desde /screener («Crea el primero en Screeners») y por el
        // subnav del hub.
        children: [{ href: '/screener', labelKey: 'nav.screener', icon: LineChart, hub: '/discover', descriptionKey: 'nav.descriptions.screener' }],
      },
      {
        href: '/mercados',
        labelKey: 'nav.items.panoramaMercado',
        icon: LineChart,
        hub: '/discover',
        descriptionKey: 'nav.descriptions.panoramaMercado',
      },
      {
        href: '/knowledge',
        labelKey: 'nav.items.knowledge',
        icon: BookOpen,
        hub: '/knowledge',
        subnavHideSelf: true,
        children: [{ href: '/knowledge-graph', labelKey: 'nav.items.grafo', icon: Share2, hub: '/knowledge' }],
      },
    ],
  },
  {
    titleKey: 'nav.sections.senales',
    items: [
      { href: '/watchlist', labelKey: 'nav.items.watchlist', icon: Star, hub: '/watchlist' },
      { href: '/insider', labelKey: 'nav.items.insider', icon: Users, hub: '/discover', descriptionKey: 'nav.descriptions.insider' },
      { href: '/ownership', labelKey: 'nav.items.ownership', icon: Landmark, hub: '/discover', descriptionKey: 'nav.descriptions.ownership' },
      {
        href: '/inversores',
        labelKey: 'nav.items.inversores',
        icon: UsersRound,
        hub: '/discover',
        descriptionKey: 'nav.descriptions.inversores',
        // Canales vive bajo /inversores (su HubNav) pero pertenece al hub de
        // Biblioteca: el subnav contextual alli es el de Conocimiento.
        children: [{ href: '/inversores/canales', labelKey: 'nav.items.canales', icon: Users, hub: '/knowledge' }],
      },
      { href: '/alerts', labelKey: 'nav.items.alertas', icon: Bell, hub: '/watchlist' },
      { href: '/propicks', labelKey: 'nav.items.propicks', icon: Lightbulb, hub: '/discover', descriptionKey: 'nav.descriptions.propicks' },
      { href: '/temas', labelKey: 'nav.items.temas', icon: LineChart, hub: '/discover', descriptionKey: 'nav.descriptions.temas' },
      { href: '/cuellos', labelKey: 'nav.items.cuellos', icon: Gauge, hub: '/discover', descriptionKey: 'nav.descriptions.cuellos' },
      { href: '/macro-calendar', labelKey: 'nav.items.calendarioMacro', icon: CalendarDays, hub: '/discover', descriptionKey: 'nav.descriptions.calendarioMacro' },
    ],
  },
  {
    // Un solo destino: sin titulo de seccion visible (showsNavSectionTitle),
    // se acabo el duplicado «Mi plan»/«Plan» (quick win UX 3).
    titleKey: 'nav.sections.miPlan',
    items: [{ href: '/plan', labelKey: 'nav.items.plan', icon: Target, hub: '/portfolio' }],
  },
  {
    titleKey: 'nav.sections.sistema',
    // /export ya no esta en el menu (sin uso; la ruta sigue existiendo). /security vive en el menu del avatar y /screener como hijo de Screeners.
    // /help es publica y sin hub: no se resalta ninguna seccion al visitarla.
    items: [
      { href: '/help', labelKey: 'nav.items.ayuda', icon: CircleHelp, hub: null },
    ],
  },
];

/**
 * Barra inferior movil: 5 destinos, nada mas. El resto del arbol sigue en el
 * menu lateral (icono de menu de la cabecera). Cada href existe en NAV_SECTIONS
 * o es la ruta del asistente.
 */
export const MOBILE_TAB_ITEMS: NavItem[] = [
  { href: '/inicio', labelKey: 'nav.items.inicio', icon: Home },
  { href: '/discover', labelKey: 'nav.items.discover', icon: Filter },
  { href: '/watchlist', labelKey: 'nav.items.watchlist', icon: Star },
  { href: '/portfolio', labelKey: 'nav.portfolio', icon: Briefcase },
  { href: '/research', labelKey: 'nav.research', icon: FileSearch },
];

/** Aplana el arbol a una lista de rutas, para buscar un href puntual. */
export function flattenNavItems(sections: NavSection[] = ROUTE_CATALOG): NavItem[] {
  return sections.flatMap((section) =>
    section.items.flatMap((item) => (item.children ? [item, ...item.children] : [item])),
  );
}

/**
 * Un href esta activo si es el mas largo que coincide con la ruta: con
 * `pathname.startsWith(href)` a secas, /portfolio/intelligence encendia
 * "Cartera" y "Cartera · Intelligence" a la vez.
 */
export function isNavItemActive(pathname: string, href: string): boolean {
  const family = sectionForRoute(pathname);
  if (NAV_SECTIONS[0].items.some((item) => item.href === href)) return family === href;
  if (href === '/') return pathname === '/';
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Coincidencia EXACTA de la ruta. `isNavItemActive` mantiene encendido el hub
 * cuando la pagina actual es una subruta; eso no convierte al hub en la pagina
 * (`aria-current="page"`). El menu usa esta funcion para decidir entre `page`
 * (destino exacto) y `true` (hub que contiene la pagina actual).
 */
export function isNavItemExact(pathname: string, href: string): boolean {
  return pathname === href;
}

/**
 * Hub de una ruta, derivado del ROUTE_CATALOG (una sola fuente): el hub es el
 * del href mas largo del catalogo que prefija la ruta. Asi /research/MSFT cae
 * en Research y /inversores/canales en Biblioteca sin listas paralelas que
 * sincronizar a mano. Ruta fuera del catalogo (/security, landing) -> null.
 */
export function sectionForRoute(pathname: string): string | null {
  const anchor = flattenNavItems()
    .filter((item) => pathname === item.href || pathname.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0];
  return anchor?.hub ?? null;
}

/** Encabezado de seccion visible solo si la seccion aporta mas de un destino. */
export function showsNavSectionTitle(section: NavSection): boolean {
  return section.titleKey !== undefined && section.items.length > 1;
}

export const POPULAR_STOCK_SYMBOLS = [
  "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
  "JPM", "V", "JNJ", "UNH", "HD", "PG", "MA", "DIS",
  "NFLX", "ADBE", "CRM", "AMD", "INTC", "PYPL", "COST",
  "PEP", "KO", "NKE", "MCD", "WMT", "BA", "GS", "UBER"
] as const;

// Opciones de onboarding (solo el valor: la etiqueta visible sale de *_LABEL_KEYS + t()).
export const INVESTMENT_GOALS = [
  { value: "growth" },
  { value: "income" },
  { value: "value" },
  { value: "speculation" },
  { value: "retirement" },
  { value: "education" }
] as const;

export const RISK_TOLERANCE_OPTIONS = [
  { value: "conservative" },
  { value: "moderate" },
  { value: "aggressive" },
  { value: "very_aggressive" }
] as const;

// Mapas valor -> clave i18n (auth.goals/risk/industries) para las opciones de onboarding.
export const INVESTMENT_GOAL_LABEL_KEYS = {
  growth: 'auth.goals.growth',
  income: 'auth.goals.income',
  value: 'auth.goals.value',
  speculation: 'auth.goals.speculation',
  retirement: 'auth.goals.retirement',
  education: 'auth.goals.education',
} as const;

export const RISK_TOLERANCE_LABEL_KEYS = {
  conservative: 'auth.risk.conservative',
  moderate: 'auth.risk.moderate',
  aggressive: 'auth.risk.aggressive',
  very_aggressive: 'auth.risk.very_aggressive',
} as const;

export const PREFERRED_INDUSTRY_LABEL_KEYS = {
  technology: 'auth.industries.technology',
  healthcare: 'auth.industries.healthcare',
  finance: 'auth.industries.finance',
  consumer: 'auth.industries.consumer',
  energy: 'auth.industries.energy',
  industrial: 'auth.industries.industrial',
  real_estate: 'auth.industries.real_estate',
  materials: 'auth.industries.materials',
  utilities: 'auth.industries.utilities',
  communication: 'auth.industries.communication',
} as const;

export const PREFERRED_INDUSTRIES = [
  { value: "technology" },
  { value: "healthcare" },
  { value: "finance" },
  { value: "consumer" },
  { value: "energy" },
  { value: "industrial" },
  { value: "real_estate" },
  { value: "materials" },
  { value: "utilities" },
  { value: "communication" }
] as const;
