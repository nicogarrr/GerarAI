import type { ReactNode } from "react";
import { CalendarTabs } from "@/components/calendar/CalendarTabs";

// Calendarios: catalizadores de cartera, macro y 8-K, y acciones corporativas
// se enlazan entre sí sin mover rutas.
export default function CalendariosLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <CalendarTabs />
      {children}
    </>
  );
}
