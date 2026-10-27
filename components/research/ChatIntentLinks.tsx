'use client';

import { Button } from '@/components/ui/button';
import { openBrain } from '@/lib/brain/open-brain';
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
        <Button key={intent.key} type="button" variant="outline" onClick={() => openBrain({ ticker, question: intent.question(ticker) })}>
          {intent.label}
        </Button>
      ))}
    </div>
  );
}
