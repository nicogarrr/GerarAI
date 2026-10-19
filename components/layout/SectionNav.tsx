'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {flattenNavItems, sectionForRoute} from '@/lib/constants';

/**
 * Subnav contextual del hub actual. En móvil va en UNA fila con scroll
 * horizontal (decisión de Nico, WhatsApp 2026-10-20 01:15: la barra de 10
 * envuelta ocupaba 4 filas, "la mitad es menú"); desde sm envuelve como antes. Se DERIVA del ROUTE_CATALOG (campo `hub`
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
 if(pathname==='/discover')return null;
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
 return <nav aria-label="Herramientas de la sección" className="-mx-4 mb-6 flex flex-nowrap gap-1.5 overflow-x-auto border-b border-gray-800 px-4 pb-3 [-ms-overflow-style:none] [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 [&::-webkit-scrollbar]:hidden">{items.map((item)=>{
  const active=item.href===current;
  return <Link key={item.href} href={item.href} aria-current={active?'page':undefined} className={`inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors ${active?'bg-teal-400/10 text-teal-300':'text-gray-400 hover:bg-gray-800 hover:text-gray-100'}`}>{item.subnavLabel??item.label}</Link>;
 })}</nav>;
}
