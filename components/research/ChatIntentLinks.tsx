'use client';

import { Button } from '@/components/ui/button';
import { openBrain } from '@/lib/brain/open-brain';
import { markEarlyOpenHydrated } from '@/lib/early-open';
import { CHAT_INTENTS } from '@/lib/research/chat-intents';

/**
 * Atajos por intención (WorldStocks punto 4). Solo formulan la pregunta y la
 * abren en el Cerebro con el ticker puesto: no añaden respuestas nuevas ni
 * texto generado.
 */
export function ChatIntentLinks({ ticker }: { ticker: string }) {
  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {CHAT_INTENTS.map((intent) => (
        <Button key={intent.key} type="button" variant="outline" ref={markEarlyOpenHydrated} data-early-open="brain" data-early-open-detail={JSON.stringify({ ticker, question: intent.question(ticker) })} onClick={() => openBrain({ ticker, question: intent.question(ticker) })}>
          {intent.label}
        </Button>
      ))}
    </div>
  );
}
