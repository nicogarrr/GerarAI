"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SECTIONS = [
  ["/inversores", "Todos"],
  ["/inversores/cartas", "Cartas"],
  ["/inversores/videos", "Vídeos"],
  ["/inversores/conceptos", "Conceptos"],
  ["/inversores/mas-compradas", "Más compradas"],
  ["/inversores/solape", "Solape"],
  ["/inversores/canales", "Canales"],
] as const;

export function HubNav() {
  const pathname = usePathname();
  const active =
    SECTIONS.find(
      ([href]) =>
        href !== "/inversores" &&
        (pathname === href || pathname.startsWith(`${href}/`)),
    )?.[0] ?? "/inversores";
  return (
    <nav
      aria-label="Secciones de Inversores"
      className="mx-auto mb-6 flex max-w-5xl flex-wrap gap-2 border-b border-gray-800 pb-3"
    >
      {SECTIONS.map(([href, label]) => (
        <Link
          aria-current={active === href ? "page" : undefined}
          className={`inline-flex min-h-11 items-center rounded-lg px-3 py-2 text-sm transition-colors md:min-h-0 ${active === href ? "bg-teal-400/10 text-teal-300" : "text-gray-400 hover:bg-gray-900 hover:text-gray-100"}`}
          href={href}
          key={href}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
