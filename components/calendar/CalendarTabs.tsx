"use client";

import Link from "next/link";
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
  // La pestaña activa es la de href más largo que encaja: /calendar/resultados
  // no debe encender también /calendar.
  const activeHref = TABS.map(([href]) => href)
    .filter((href) => pathname === href || pathname.startsWith(`${href}/`))
    .sort((a, b) => b.length - a.length)[0];
  return (
    <nav
      aria-label="Calendarios"
      className="mx-auto flex max-w-7xl flex-wrap gap-2 px-4 pt-4 sm:px-6"
    >
      {TABS.map(([href, label]) => {
        const active = href === activeHref;
        return (
          <Link
            aria-current={active ? "page" : undefined}
            className={`min-h-11 rounded-lg px-3 py-2 text-sm transition-colors ${active ? "bg-teal-300/10 text-teal-300" : "text-gray-400 hover:bg-gray-900 hover:text-gray-100"}`}
            href={href}
            key={href}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
