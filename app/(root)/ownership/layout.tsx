import type { ReactNode } from "react";

// La navegación de Descubrir (SectionNav) ya incluye esta sección: sin barra propia.
export default function Layout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
