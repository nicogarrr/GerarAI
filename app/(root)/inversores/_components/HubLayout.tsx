import { Suspense, type ReactNode } from "react";

import { HubNav } from "./HubNav";

// Layout compartido del hub Inversores/Señales fusionado: /inversores,
// /insider y /ownership llevan la misma barra HubNav (4 pestañas), envuelta
// en Suspense porque HubNav lee useSearchParams. Antes cada layout copiaba
// este mismo JSX.
export function HubLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <Suspense fallback={null}>
        <HubNav />
      </Suspense>
      {children}
    </>
  );
}
