import type { ReactNode } from "react";

import { CalendariosLayout } from "@/components/calendar/CalendariosLayout";

// Calendarios: catalizadores de cartera, macro y 8-K, y acciones corporativas
// se enlazan entre sí sin mover rutas. El JSX compartido vive en
// components/calendar/CalendariosLayout.tsx.
export default function Layout({ children }: { children: ReactNode }) {
  return <CalendariosLayout>{children}</CalendariosLayout>;
}
