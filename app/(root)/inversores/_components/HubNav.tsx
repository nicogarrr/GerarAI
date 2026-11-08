"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT } from "@/lib/i18n/client";

// Barra final del hub Inversores/Señales: 4 destinos, decidido por Nico
// (WhatsApp 2026-10-20 00:59, Opción A). En móvil UNA sola fila con scroll
// horizontal si no cabe: "la mitad es menú" (Nico, WhatsApp 2026-10-20 01:15),
// la doble barra envuelta ocupaba ~7 filas antes del contenido.
const SECTIONS = [
  ["/inversores"],
  ["/ownership", "13F"],
  ["/insider", "Insiders"],
  ["/inversores/aprender"],
] as const;

// Las sub-páginas de aprendizaje cuelgan de Aprender (PR 3 las fusiona allí).
const LEARN_PREFIXES = [
  "/inversores/aprender",
  "/inversores/cartas",
  "/inversores/videos",
  "/inversores/conceptos",
  "/inversores/canales",
];

export function HubNav() {
  const pathname = usePathname();
  const t = useT();
  const active = LEARN_PREFIXES.some((prefix) => pathname.startsWith(prefix))
    ? "/inversores/aprender"
    : (SECTIONS.find(
        ([href]) =>
          href !== "/inversores" &&
          (pathname === href || pathname.startsWith(`${href}/`)),
      )?.[0] ?? (pathname.startsWith("/inversores") ? "/inversores" : ""));
  return (
    <nav
      aria-label={t('investors.nav.aria')}
      className="mx-auto mb-6 flex max-w-5xl flex-nowrap gap-2 overflow-x-auto border-b border-gray-800 pb-3 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
    >
      {SECTIONS.map(([href, fixed]) => (
        <Link
          aria-current={active === href ? "page" : undefined}
          className={`inline-flex min-h-11 shrink-0 items-center whitespace-nowrap rounded-lg px-3 py-2 text-sm transition-colors md:min-h-0 ${active === href ? "bg-teal-400/10 text-teal-300" : "text-gray-400 hover:bg-gray-900 hover:text-gray-100"}`}
          href={href}
          key={href}
        >
          {fixed ?? (href === '/inversores' ? t('investors.nav.investors') : t('investors.nav.learn'))}
        </Link>
      ))}
    </nav>
  );
}
