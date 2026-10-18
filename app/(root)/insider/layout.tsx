import { Suspense, type ReactNode } from "react";
import { HubNav } from "../inversores/_components/HubNav";

// Quién compra: Insiders (Form 4), 13F e Inversores comparten una sola barra.
export default function QuienCompraLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <Suspense fallback={null}>
        <HubNav />
      </Suspense>
      {children}
    </>
  );
}
