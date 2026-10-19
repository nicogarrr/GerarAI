import { Suspense, type ReactNode } from "react";

import { HubNav } from "../inversores/_components/HubNav";

// /insider forma parte del hub Inversores/Senales fusionado (decision de Nico,
// WhatsApp 2026-10-20 00:59): misma barra HubNav que /inversores, en vez del
// subnav generico de Descubrir (SectionNav excluye esta ruta). Revierte la
// mitad de #1924 que dejo estas paginas sin barra propia.
export default function Layout({ children }: { children: ReactNode }) {
  return (
    <>
      <Suspense fallback={null}>
        <HubNav />
      </Suspense>
      {children}
    </>
  );
}
