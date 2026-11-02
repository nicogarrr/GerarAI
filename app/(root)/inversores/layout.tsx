import type { ReactNode } from "react";

import { HubLayout } from "./_components/HubLayout";

export default function InvestorsLayout({ children }: { children: ReactNode }) {
  return <HubLayout>{children}</HubLayout>;
}
