"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

const TABS = [
  ["/portfolio", "Cartera"],
  ["/calendar/resultados", "Resultados"],
  ["/calendar/suscripcion", "Suscribir"],
  ["/calendar", "Catalizadores"],
  ["/macro-calendar", "Macro y 8-K"],
  ["/corporate-actions", "Acciones corp."],
] as const;

export function CalendarTabs() {
  const pathname = usePathname();
  const navRef = useRef<HTMLElement>(null);
  // Indicador de más pestañas fuera de pantalla: en 390px la tira de 5 pestañas
  // se cortaba sin ninguna pista de que había más.
  const [more, setMore] = useState({ left: false, right: false });
  const updateMore = useCallback(() => {
    const nav = navRef.current;
    if (!nav) return;
    const left = nav.scrollLeft > 4;
    const right = nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 4;
    setMore((prev) => (prev.left === left && prev.right === right ? prev : { left, right }));
  }, []);
  useEffect(() => {
    updateMore();
    window.addEventListener("resize", updateMore);
    return () => window.removeEventListener("resize", updateMore);
  }, [updateMore]);
  useEffect(() => {
    const nav = navRef.current;
    const active = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (nav && active) {
      // Scroll mínimo "nearest": solo se desplaza si la pestaña activa no es
      // ya visible entera. Centrar siempre recortaba la primera pestaña en
      // móvil aunque la activa cupiera sin desplazamiento.
      const left = active.offsetLeft - nav.offsetLeft;
      const right = left + active.offsetWidth;
      if (left < nav.scrollLeft) {
        nav.scrollLeft = Math.max(0, left - 8);
      } else if (right > nav.scrollLeft + nav.clientWidth) {
        nav.scrollLeft = right - nav.clientWidth + 8;
      }
    }
    updateMore();
  }, [pathname, updateMore]);
  // La pestaña activa es la de href más largo que encaja: /calendar/resultados
  // no debe encender también /calendar.
  const activeHref = TABS.map(([href]) => href)
    .filter((href) => pathname === href || pathname.startsWith(`${href}/`))
    .sort((a, b) => b.length - a.length)[0];
  return (
    <div className="relative mx-auto mb-4 w-full min-w-0 max-w-7xl">
    <nav
      ref={navRef}
      onScroll={updateMore}
      aria-label="Calendarios"
      className="flex w-full min-w-0 flex-nowrap gap-1 overflow-x-auto border-b border-gray-800 px-4 py-2 sm:px-6"
    >
      {TABS.map(([href, label]) => {
        const active = href === activeHref;
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors ${active ? "bg-teal-300/10 text-teal-300" : "text-gray-400 hover:bg-gray-900 hover:text-gray-100"}`}
            href={href}
            scroll={false}
            key={href}
          >
            {label}
          </Link>
        );
      })}
    </nav>
    {more.left && (
      <span aria-hidden="true" data-testid="calendar-tabs-fade-left" className="pointer-events-none absolute inset-y-0 left-0 w-8 bg-gradient-to-r from-background to-transparent" />
    )}
    {more.right && (
      <span aria-hidden="true" data-testid="calendar-tabs-fade-right" className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-background to-transparent" />
    )}
    </div>
  );
}
