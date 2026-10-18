'use client';
import Link from 'next/link';
import {usePathname} from 'next/navigation';
import {flattenNavItems, sectionForRoute} from '@/lib/constants';

/**
 * Subnav contextual del hub actual. Se DERIVA del ROUTE_CATALOG (campo `hub`
 * de cada item): una sola fuente para menu, migas, buscador y este subnav, en
 * vez de un mapa de rutas paralelo que se quedaba desactualizado.
 *
 * Dos huecos a proposito:
 * - /discover ya ES la portada del hub: mostrar su propio indice como subnav
 *   repite la pagina.
 * - /inversores tiene su HubNav propio en app/(root)/inversores/layout.tsx:
 *   pintar aqui tambien el grupo apilaba dos barras seguidas (doble subnav).
 */
export default function SectionNav(){
 const pathname=usePathname();
 if(pathname==='/discover'||pathname.startsWith('/inversores'))return null;
 const section=sectionForRoute(pathname);
 if(!section)return null;
 const items=flattenNavItems().filter((item)=>item.hub===section&&!(item.href===pathname&&item.subnavHideSelf));
 if(items.length<2)return null;
 return <nav aria-label="Herramientas de la sección" className="mb-6 flex flex-wrap gap-1.5 border-b border-gray-800 pb-3">{items.map((item)=>{
  const active=item.href===pathname;
  return <Link key={item.href} href={item.href} aria-current={active?'page':undefined} className={`inline-flex min-h-11 items-center rounded-lg px-3 py-2 text-sm transition-colors ${active?'bg-teal-400/10 text-teal-300':'text-gray-400 hover:bg-gray-800 hover:text-gray-100'}`}>{item.subnavLabel??item.label}</Link>;
 })}</nav>;
}
