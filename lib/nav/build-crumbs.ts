// @ts-expect-error TS5097: extensión explícita para node --experimental-strip-types (guards).
import { flattenNavItems, NAV_SECTIONS, ROUTE_CATALOG, type NavItem } from '../constants.ts';
import type { TranslationKey } from '@/lib/i18n/messages';

/** Nombre canonico de cada hub: el del menu lateral (NAV_SECTIONS). */
const HUB_LABEL_KEYS = new Map(NAV_SECTIONS.flatMap((section) => section.items).map((item) => [item.href, item.labelKey]));

// href opcional: los niveles que no son una ruta real (la seccion del menu)
// se muestran como texto plano - un enlace a `#Seccion` no navega a nada (F141).
// labelKey: clave i18n (nav.*) a resolver con t() en el componente; rawLabel:
// texto ya resuelto (slug humanizado, ticker, override en vivo del componente).
export type Crumb = { href?: string; labelKey?: TranslationKey; rawLabel?: string };

/** Sub-rutas con nombre legible (claves i18n); el resto se muestra tal cual (ticker, screenId). */
const SUBROUTE_LABEL_KEYS: Record<string, TranslationKey> = {
  'financial-terminal': 'nav.subroutes.terminalFinanciero',
  'driver-assumptions': 'nav.subroutes.driverAssumptions',
  'decision-lessons': 'nav.subroutes.decisionLessons',
  'management-credibility': 'nav.subroutes.credibilidadDirectiva',
  // Fuera del nav principal (quick win UX 3); la miga sigue legible.
  // Modulo Inversores: sub-paginas fijas (no son un slug de inversor).
  // Sub-pestaña de Calendarios (#1777): sin entrada, la miga salia cruda.
  'suscripcion': 'nav.subroutes.suscripcion',
  'resultados': 'nav.subroutes.resultados',
  // Sub-paginas de ficha: sin entrada la miga salia en minuscula cruda
  // ("… > ASTS > tesis") mientras el H1 dice "Tesis de inversión".
  'tesis': 'nav.subroutes.tesis',
  'shorts': 'nav.subroutes.cortos',
  'filings': 'nav.subroutes.filings',
};

/** Slug sin etiqueta propia (p. ej. "warren-buffett") -> "Warren Buffett" en vez del slug crudo. */
function humanizeSlug(segment: string): string {
  if (!/^[a-z]+(?:-[a-z]+)+$|^[a-z]{4,}$/.test(segment)) return segment;
  return segment
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/** El dashboard vive en `/inicio` porque `/` es la landing pública. */
const HOME_HREF = '/inicio';

/**
 * Migas derivadas de `NAV_SECTIONS`: la ruta se ancla al href mas largo que
 * coincida, y los segmentos sobrantes se anaden como migas propias. Asi
 * /research/MSFT/financial-terminal se lee "Analisis > Research > MSFT >
 * Terminal financiero" sin que ninguna pagina tenga que mantener su propia
 * jerarquia, y las rutas huerfanas del menu (que antes no existian en ningun
 * sitio) tienen contexto.
 *
 * Hijos que cruzan de hub (/inversores/canales cuelga por URL de Inversores
 * pero pertenece al hub Biblioteca): el nivel intermedio se toma del HUB del
 * item, no del padre por URL. Sin esto las migas decian "Señales > Inversores
 * > Canales" mientras el sidebar resaltaba Biblioteca y el subnav era el de
 * Conocimiento: dos respuestas contradictorias de "donde estoy". Todo se
 * deriva del ROUTE_CATALOG (`hub` de cada item), sin lista de excepciones.
 */
export function buildCrumbs(pathname: string): Crumb[] {
  const items = flattenNavItems();
  const parentOf = new Map<string, NavItem>();
  const sectionOf = new Map<string, TranslationKey | undefined>();
  for (const section of ROUTE_CATALOG) {
    for (const item of section.items) {
      sectionOf.set(item.href, section.titleKey);
      for (const node of [item, ...(item.children ?? [])]) {
        parentOf.set(node.href, item);
        if (!sectionOf.has(node.href)) sectionOf.set(node.href, section.titleKey);
      }
    }
  }

  if (pathname === HOME_HREF) return [{ href: HOME_HREF, labelKey: 'nav.items.inicio' }];

  // Ancla: el href mas largo que sea prefijo de la ruta.
  const anchor = items
    .filter((item) => item.href !== HOME_HREF && (pathname === item.href || pathname.startsWith(`${item.href}/`)))
    .sort((a, b) => b.href.length - a.href.length)[0];

  const crumbs: Crumb[] = [{ href: HOME_HREF, labelKey: 'nav.items.inicio' }];

  if (!anchor) return crumbs;

  // Padre intermedio: el declarado por URL, salvo que el hijo pertenezca a
  // OTRO hub; entonces manda el item del hub del propio ancla (una sola
  // fuente: el campo `hub` del catalogo).
  const urlParent = parentOf.get(anchor.href);
  const crossesHub = Boolean(urlParent && anchor.hub && urlParent.hub !== anchor.hub);
  const crumbParent = crossesHub
    ? (items.find((item) => item.href === anchor.hub) ?? urlParent)
    : urlParent;

  const sectionTitleKey = sectionOf.get((crumbParent ?? anchor).href);
  if (sectionTitleKey && sectionTitleKey !== 'nav.sections.principal') {
    crumbs.push({ labelKey: sectionTitleKey });
  }
  // Cualquier nivel que sea un HUB (padre por cruce o el propio ancla) se
  // nombra como en el menu lateral (NAV_SECTIONS): una sola etiqueta por
  // ruta (/knowledge y /portfolio dicen «Biblioteca» y «Resumen» tambien en
  // el catalogo). Si el nombre canonico repite el de la seccion (/portfolio
  // en Cartera), se conserva la etiqueta del catalogo para no duplicar
  // niveles.
  // Dedupe por equivalencia de TEXTO entre el titulo de seccion y el nombre
  // canonico del hub: con claves i18n no se puede comparar el literal (cada
  // locale lo resuelve distinto), asi que la equivalencia se declara aqui.
  // /portfolio en la seccion Cartera: ambos dicen «Cartera»; se conserva la
  // etiqueta del catalogo («Resumen») para no duplicar niveles.
  const SECTION_TITLE_EQUALS_HUB_NAME: Record<string, TranslationKey> = {
    'nav.sections.cartera': 'nav.portfolio',
  };
  const canonicalNameKey = (href: string) => {
    const key = HUB_LABEL_KEYS.get(href);
    return key && SECTION_TITLE_EQUALS_HUB_NAME[sectionTitleKey ?? ''] !== key && key !== sectionTitleKey ? key : undefined;
  };
  // Si el ancla es un hijo declarado (/research/news), su padre (/research)
  // es un nivel real de la jerarquia: sin el la miga saltaba de la seccion
  // al hijo ("Analisis > Noticias") y el padre dejaba de ser alcanzable.
  if (crumbParent && crumbParent.href !== anchor.href) {
    crumbs.push({ href: crumbParent.href, labelKey: canonicalNameKey(crumbParent.href) ?? crumbParent.labelKey });
  }
  crumbs.push({ href: anchor.href, labelKey: canonicalNameKey(anchor.href) ?? anchor.labelKey });

  // Segmentos restantes: hijo declarado del nav, sub-ruta con nombre o el
  // propio identificador (ticker, screenId).
  const rest = pathname.slice(anchor.href.length).split('/').filter(Boolean);
  let parent = urlParent;
  rest.forEach((segment, index) => {
    const pathSoFar = `${anchor.href}/${rest.slice(0, index + 1).join('/')}`;
    const declared = parent?.children?.find((child) => child.href === pathSoFar);
    if (declared) {
      crumbs.push({ href: declared.href, labelKey: declared.labelKey });
      parent = declared;
      return;
    }
    const labelKey = SUBROUTE_LABEL_KEYS[segment];
    crumbs.push(labelKey ? { href: pathSoFar, labelKey } : { href: pathSoFar, rawLabel: anchor.href === '/inversores' ? humanizeSlug(segment) : segment });
  });

  return crumbs;
}
