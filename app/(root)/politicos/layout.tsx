import type { ReactNode } from "react";

import { HubLayout } from "../inversores/_components/HubLayout";

// /politicos vive en el hub Inversores/Señales, junto a 13F e Insiders.
export default function Layout({ children }: { children: ReactNode }) {
  return <HubLayout>{children}</HubLayout>;
}
