"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

const TABS = [
  ["/calendar/resultados", "Resultados"],
  ["/calendar/suscripcion", "Suscribir"],
  ["/calendar", "Catalizadores"],
  ["/macro-calendar", "Macro y 8-K"],
  ["/corporate-actions", "Acciones corp."],
] as const;

export function CalendarTabs() {
  const pathname = usePathname();
  const navRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const nav = navRef.current;
    const active = nav?.querySelector<HTMLElement>('[aria-current="page"]');
    if (nav && active) nav.scrollLeft = Math.max(0, active.offsetLeft - nav.offsetLeft - (nav.clientWidth - active.clientWidth) / 2);
  }, [pathname]);
  // La pestaña activa es la de href más largo que encaja: /calendar/resultados
  // no debe encender también /calendar.
  const activeHref = TABS.map(([href]) => href)
    .filter((href) => pathname === href || pathname.startsWith(`${href}/`))
    .sort((a, b) => b.length - a.length)[0];
  return (
    <nav
      ref={navRef}
      aria-label="Calendarios"
      className="mx-auto mb-4 flex w-full min-w-0 max-w-7xl flex-nowrap gap-1 overflow-x-auto border-b border-gray-800 px-4 py-2 sm:px-6"
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
  );
}
