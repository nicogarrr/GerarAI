'use client';

import { Search } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { openBrain } from '@/lib/brain/open-brain';

/** Pregunta de la ficha: no tiene chat propio, la lleva al Cerebro con el ticker puesto. */
export default function BrainAskForm({ ticker }: { ticker: string }) {
  const [question, setQuestion] = useState('');
  return (
    <form
      className="flex flex-col gap-3 sm:flex-row"
      onSubmit={(event) => {
        event.preventDefault();
        const text = question.trim();
        if (text.length < 3) return;
        openBrain({ ticker, question: text });
        setQuestion('');
      }}
    >
      <Input
        name="chat"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        placeholder={`Pregunta sobre ${ticker} al Cerebro`}
        aria-label={`Pregunta sobre ${ticker}`}
        minLength={3}
        maxLength={2000}
        required
        className="h-11 text-base sm:h-9 sm:text-sm"
      />
      <Button type="submit" className="min-h-[44px] sm:min-h-0">
        <Search aria-hidden="true" className="mr-2 h-4 w-4" />
        Preguntar
      </Button>
    </form>
  );
}
