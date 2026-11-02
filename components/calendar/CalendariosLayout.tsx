import type { ReactNode } from "react";

import { CalendarTabs } from "@/components/calendar/CalendarTabs";

// Calendarios: catalizadores de cartera, macro y 8-K, y acciones corporativas
// se enlazan entre sí sin mover rutas. Layout compartido de /calendar,
// /macro-calendar y /corporate-actions: los tres montaban el mismo JSX
// (CalendarTabs + children) copiado.
export function CalendariosLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <CalendarTabs />
      {children}
    </>
  );
}
