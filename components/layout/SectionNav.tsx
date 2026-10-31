'use client';
import {ChevronDown, ChevronUp} from 'lucide-react';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {useEffect, useState} from 'react';
import {flattenNavItems, sectionForRoute} from '@/lib/constants';
import {OverflowScrollRegion} from '@/components/ui/overflow-scroll-region';
import { useT } from '@/lib/i18n/client';

const CALENDAR_ROUTES=['/calendar','/macro-calendar','/corporate-actions'];

/**
 * Subnav contextual del hub actual. En móvil va PLEGADO en una línea: la
 * pestaña actual con chevron que despliega el resto (decisión de Nico,
 * WhatsApp 2026-10-20 01:34: "posibilidad de esconder y desplegar esto de
 * arriba en todas las pestañas"). El estado se recuerda en localStorage.
 * El desplegable funciona en todos los tamaños; la lista envuelve desde sm. Se DERIVA del ROUTE_CATALOG (campo `hub`
 * de cada item): una sola fuente para menu, migas, buscador y este subnav, en
 * vez de un mapa de rutas paralelo que se quedaba desactualizado.
 *
 * Tres huecos a proposito:
 * - /discover ya ES la portada del hub: mostrar su propio indice como subnav
 *   repite la pagina.
 * - /inversores tiene su HubNav propio en app/(root)/inversores/layout.tsx:
 *   pintar aqui tambien el grupo apilaba dos barras seguidas (doble subnav).
 * - /inversores, /insider y /ownership comparten el HubNav del hub fusionado
 *   (4 pestañas): se excluyen arriba por ruta. /inversores/canales no, porque
 *   pertenece al hub Biblioteca.
 */
export default function SectionNav(){
 const pathname=usePathname();
 const t=useT();
 const [open,setOpen]=useState(false);
 useEffect(()=>{
  // Preferencia persistida (almacén externo del navegador): se lee tras
  // montar y el setState no es síncrono dentro del efecto.
  queueMicrotask(() => {
   try { setOpen(window.localStorage.getItem('subnav-seccion')==='abierto'); } catch { /* Storage may be disabled. */ }
  });
 },[]);
 const toggle=()=>{
  const next=!open;
  setOpen(next);
  try { window.localStorage.setItem('subnav-seccion',next?'abierto':'cerrado'); } catch { /* Keep the toggle usable without storage. */ }
 };

 if(pathname==='/discover')return null;
 // Calendarios (/calendar, /macro-calendar, /corporate-actions) ya llevan su propia
 // barra de pestañas (CalendarTabs, con «Cartera» como primera): dos capas de
 // navegación seguidas empujaban el contenido bajo el pliegue en móvil.
 if(CALENDAR_ROUTES.some((route)=>pathname===route||pathname.startsWith(`${route}/`)))return null;
 // Hub Inversores/Senales fusionado (decision de Nico, WhatsApp 2026-10-20
 // 00:59): /inversores, /insider y /ownership comparten el HubNav de 4
 // pestañas; pintar aqui el subnav de Descubrir era la doble barra.
 // /inversores/canales se queda fuera: pertenece al hub Biblioteca.
 if(pathname==='/insider'||pathname.startsWith('/insider/')||pathname==='/ownership'||pathname.startsWith('/ownership/'))return null;
 if((pathname==='/inversores'||pathname.startsWith('/inversores/'))&&!pathname.startsWith('/inversores/canales'))return null;
 const section=sectionForRoute(pathname);
 if(!section)return null;
 const items=flattenNavItems().filter((item)=>item.hub===section&&!(item.href===pathname&&item.subnavHideSelf));
 if(items.length<2)return null;
 // Activo = la ruta mas especifica que contiene la pagina actual (una ficha /research/AAPL cuelga de Empresas).
 const current=items.filter((item)=>pathname===item.href||pathname.startsWith(`${item.href}/`)).sort((a,b)=>b.href.length-a.href.length)[0]?.href;
 // Pantalla de detalle (una ficha /research/AAPL, un screen guardado): cuelga
 // de una herramienta del hub pero NO es esa herramienta. Ahi el subnav del hub
 // era la tercera capa de navegacion sobre la propia de la pagina (migas y
 // pestañas de la ficha) y empujaba la cotizacion bajo el pliegue en movil.
 // Las migas ya llevan de vuelta a la herramienta.
 if(current&&current!==pathname)return null;
 const currentItem=items.find((item)=>item.href===current);
 // Activo neutro (gris claro sobre surface-2), igual que el item activo del
 // sidebar: el teal queda para acciones y datos, no para "estoy aqui".
 return <div className="-mx-4 mb-4 border-b border-gray-800 px-4 pb-1 sm:mx-0 sm:mb-6 sm:border-b-0 sm:px-0 sm:pb-0">
  <button aria-controls="subnav-seccion-lista" aria-expanded={open} className="-ml-3 inline-flex min-h-11 items-center gap-1 rounded-lg px-3 py-2 text-sm font-medium text-gray-200 sm:hidden" onClick={toggle} type="button">
   {currentItem?t(currentItem.subnavLabelKey??currentItem.labelKey):t('shell.sectionNav.sections')}
   {open?<ChevronUp aria-hidden className="text-gray-500" size={16}/>:<ChevronDown aria-hidden className="text-gray-500" size={16}/>}
  </button>
  <nav aria-label={t('shell.sectionNav.ariaLabel')} className={`${open?'block':'hidden'} sm:block sm:border-b sm:border-gray-800 sm:pb-3`} id="subnav-seccion-lista"><OverflowScrollRegion hint={t('shell.sectionNav.scrollHint')} label={t('shell.sectionNav.ariaLabel')} regionClassName="[-ms-overflow-style:none] [scrollbar-width:none] sm:overflow-visible [&::-webkit-scrollbar]:hidden"><div className="flex flex-nowrap gap-1.5 sm:flex-wrap">{items.map((item)=>{
   const active=item.href===current;
   return <Link key={item.href} href={item.href} scroll={false} aria-current={active?'page':undefined} className={`inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors ${active?'bg-gray-800 font-medium text-gray-100':'text-gray-400 hover:bg-gray-800/60 hover:text-gray-100'}`}>{t(item.subnavLabelKey??item.labelKey)}</Link>;
  })}</div></OverflowScrollRegion></nav>
 </div>;
}
