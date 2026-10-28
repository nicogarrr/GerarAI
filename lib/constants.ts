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

// Mensajes de error comunes. En espanol: los de AUTH_* los muestra el usuario
// en /sign-in y /sign-up a traves de las server actions, y una app es-ES no
// puede mostrar "Authentication failed" en el formulario de acceso.
export const ERROR_MESSAGES = {
  AUTH_FAILED: 'No se pudo iniciar sesión. Revisa tu correo y tu contraseña.',
  AUTH_UNAVAILABLE: 'El servicio de autenticación no está disponible ahora mismo. Inténtalo de nuevo en unos minutos.',
  INVALID_SYMBOL: 'Símbolo con formato no válido. Debe tener entre 1 y 10 caracteres y solo letras, números, puntos y guiones.',
  MISSING_API_KEY: 'Este servicio no está configurado en este servidor.',
  RATE_LIMIT_EXCEEDED: 'Has superado el límite de peticiones. Inténtalo de nuevo en unos minutos.',
  DATABASE_ERROR: 'No se pudo conectar con la base de datos. Inténtalo de nuevo.',
  EXTERNAL_API_ERROR: 'No se pudieron obtener los datos del servicio externo.',
  NOT_FOUND: 'No se encontró el recurso solicitado.',
  VALIDATION_ERROR: 'Los datos introducidos no son válidos.',
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
  label: string;
  icon: LucideIcon;
  /**
   * Hub primario (una de las 6 entradas de NAV_SECTIONS) al que pertenece la
   * ruta: decide el resaltado del menu y el subnav contextual (SectionNav).
   * `null` = sin hub (destinos de apoyo como /help): no se resalta nada.
   */
  hub?: string | null;
  /** Descripcion de una linea para tarjetas de hub (/discover). */
  description?: string;
  /**
   * Etiqueta corta solo para el subnav contextual (SectionNav), cuando la
   * etiqueta del catalogo (alineada con el H1) repetiria el nombre de la
   * seccion: /research se anuncia como «Empresas» dentro de Research.
   * Migas, buscador y /discover siguen usando `label`.
   */
  subnavLabel?: string;
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
  title: string;
  items: NavItem[];
};

export const NAV_SECTIONS: NavSection[] = [{
  title: '',
  items: [
    { href: '/inicio', label: 'Inicio', icon: Home },
    { href: '/portfolio', label: 'Cartera', icon: Briefcase },
    { href: '/research', label: 'Research', icon: FileSearch },
    { href: '/discover', label: 'Descubrir', icon: Filter },
    { href: '/watchlist', label: 'Watchlist', icon: Star },
    { href: '/knowledge', label: 'Biblioteca', icon: BookOpen },
  ],
}];

export const ROUTE_CATALOG: NavSection[] = [
  {
    title: 'Principal',
    items: [
      { href: '/inicio', label: 'Inicio', icon: Home, hub: '/inicio' },
      { href: '/discover', label: 'Descubrir', icon: Filter, hub: '/discover' },
    ],
  },
  {
    title: 'Cartera',
    items: [
      { href: '/portfolio', label: 'Resumen', icon: Briefcase, hub: '/portfolio', subnavHideSelf: true },
      { href: '/portfolio/intelligence', label: 'Inteligencia', icon: Sparkles, hub: '/portfolio' },
      { href: '/risk', label: 'Exposiciones', icon: Gauge, hub: '/portfolio' },
      { href: '/taxes', label: 'Impuestos', icon: Receipt, hub: '/portfolio' },
      { href: '/corporate-actions', label: 'Acciones corp.', icon: Building2, hub: '/portfolio' },
      { href: '/calendar', label: 'Calendario', icon: CalendarDays, hub: '/portfolio' },
      { href: '/portfolio/stress', label: 'Estrés histórico', icon: LineChart, hub: '/portfolio' },
      { href: '/paper-trading', label: 'Cuenta demo', icon: FlaskConical, hub: '/portfolio' },
    ],
  },
  {
    title: 'Análisis',
    items: [
      {
        href: '/research',
        label: 'Research',
        icon: FileSearch,
        hub: '/research',
        subnavLabel: 'Empresas',
        children: [
          { href: '/research/news', label: 'Noticias', icon: Newspaper, hub: '/research' },
          { href: '/research/sources', label: 'Fuentes', icon: Library, hub: '/research' },
        ],
      },
      {
        href: '/screeners',
        label: 'Screeners',
        icon: Filter,
        hub: '/discover',
        description: 'Busca con métricas y filtros guardados.',
        children: [{ href: '/screener', label: 'Mercado', icon: LineChart, hub: '/discover', description: 'Explora empresas por sector y mira subidas, bajadas y más activas.' }],
      },
      {
        href: '/mercados',
        label: 'Mercados',
        icon: LineChart,
        hub: '/discover',
        description: 'Índices, futuros, acciones, materias primas y divisas con la hora de cada cotización.',
      },
      {
        href: '/knowledge',
        label: 'Biblioteca',
        icon: BookOpen,
        hub: '/knowledge',
        subnavHideSelf: true,
        children: [{ href: '/knowledge-graph', label: 'Grafo', icon: Share2, hub: '/knowledge' }],
      },
    ],
  },
  {
    title: 'Señales',
    items: [
      { href: '/watchlist', label: 'Watchlist', icon: Star, hub: '/watchlist' },
      { href: '/insider', label: 'Insider', icon: Users, hub: '/discover', description: 'Compras declaradas por directivos en Form 4.' },
      { href: '/ownership', label: '13F', icon: Landmark, hub: '/discover', description: 'Posiciones declaradas por los grandes fondos en el Form 13F.' },
      {
        href: '/inversores',
        label: 'Inversores',
        icon: UsersRound,
        hub: '/discover',
        description: 'Carteras declaradas y cambios en los filings.',
        // Canales vive bajo /inversores (su HubNav) pero pertenece al hub de
        // Biblioteca: el subnav contextual alli es el de Conocimiento.
        children: [{ href: '/inversores/canales', label: 'Canales', icon: Users, hub: '/knowledge' }],
      },
      { href: '/alerts', label: 'Alertas', icon: Bell, hub: '/watchlist' },
      { href: '/propicks', label: 'ProPicks', icon: Lightbulb, hub: '/discover', description: 'Ranking, reglas de selección y backtest.' },
      { href: '/temas', label: 'Temas', icon: LineChart, hub: '/discover', description: 'Rentabilidad YTD y 1M de temas de mercado.' },
      { href: '/cuellos', label: 'Cuellos de botella', icon: Gauge, hub: '/discover', description: 'Escasez detectada en las fuentes y candidatos inferidos.' },
      { href: '/macro-calendar', label: 'Calendario macro', icon: CalendarDays, hub: '/discover', description: 'FOMC, IPC y empleo, y resúmenes de tus 8-K.' },
    ],
  },
  {
    // Un solo destino: sin titulo de seccion visible (showsNavSectionTitle),
    // se acabo el duplicado «Mi plan»/«Plan» (quick win UX 3).
    title: 'Mi plan',
    items: [{ href: '/plan', label: 'Plan', icon: Target, hub: '/portfolio' }],
  },
  {
    title: 'Sistema',
    // /export ya no esta en el menu (sin uso; la ruta sigue existiendo). /security vive en el menu del avatar y /screener como hijo de Screeners.
    // /help es publica y sin hub: no se resalta ninguna seccion al visitarla.
    items: [
      { href: '/help', label: 'Ayuda', icon: CircleHelp, hub: null },
    ],
  },
];

/**
 * Barra inferior movil: 5 destinos, nada mas. El resto del arbol sigue en el
 * menu lateral (icono de menu de la cabecera). Cada href existe en NAV_SECTIONS
 * o es la ruta del asistente.
 */
export const MOBILE_TAB_ITEMS: NavItem[] = [
  { href: '/inicio', label: 'Inicio', icon: Home },
  { href: '/discover', label: 'Descubrir', icon: Filter },
  { href: '/watchlist', label: 'Watchlist', icon: Star },
  { href: '/portfolio', label: 'Cartera', icon: Briefcase },
  { href: '/research', label: 'Research', icon: FileSearch },
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
  return section.title !== '' && section.items.length > 1;
}

export const POPULAR_STOCK_SYMBOLS = [
  "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
  "JPM", "V", "JNJ", "UNH", "HD", "PG", "MA", "DIS",
  "NFLX", "ADBE", "CRM", "AMD", "INTC", "PYPL", "COST",
  "PEP", "KO", "NKE", "MCD", "WMT", "BA", "GS", "UBER"
] as const;

// Onboarding options
export const INVESTMENT_GOALS = [
  { value: "growth", label: "Crecimiento a largo plazo" },
  { value: "income", label: "Ingresos por dividendos" },
  { value: "value", label: "Value Investing" },
  { value: "speculation", label: "Trading especulativo" },
  { value: "retirement", label: "Ahorro para jubilación" },
  { value: "education", label: "Aprender a invertir" }
] as const;

export const RISK_TOLERANCE_OPTIONS = [
  { value: "conservative", label: "Conservador - Mínimo riesgo" },
  { value: "moderate", label: "Moderado - Balance riesgo/retorno" },
  { value: "aggressive", label: "Agresivo - Alto riesgo, alto retorno" },
  { value: "very_aggressive", label: "Muy agresivo - Máximo potencial" }
] as const;

export const PREFERRED_INDUSTRIES = [
  { value: "technology", label: "Tecnología" },
  { value: "healthcare", label: "Salud" },
  { value: "finance", label: "Finanzas" },
  { value: "consumer", label: "Consumo" },
  { value: "energy", label: "Energía" },
  { value: "industrial", label: "Industrial" },
  { value: "real_estate", label: "Inmobiliario" },
  { value: "materials", label: "Materiales" },
  { value: "utilities", label: "Servicios públicos" },
  { value: "communication", label: "Comunicación" }
] as const;
