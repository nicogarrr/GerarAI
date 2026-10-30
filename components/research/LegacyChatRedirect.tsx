'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { openBrain } from '@/lib/brain/open-brain';

/**
 * Enlaces antiguos `?view=chat&chat=<pregunta>`: abren el Cerebro con esa
 * pregunta y limpian el parámetro, sin llamar al motor desde el servidor.
 */
export default function LegacyChatRedirect({ ticker, question }: { ticker: string; question?: string }) {
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    const text = question?.trim();
    if (!text) return;
    openBrain({ ticker, question: text.slice(0, 2000) });
    router.replace(`${pathname}?view=fuentes#chat`, { scroll: false });
  }, [ticker, question, pathname, router]);
  return null;
}
