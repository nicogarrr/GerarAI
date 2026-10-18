'use client';

import Form from 'next/form';
import { Loader2, Search } from 'lucide-react';
import { useFormStatus } from 'react-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function Submit() {
  const { pending } = useFormStatus();
  return (
    <Button type="submit" disabled={pending} aria-busy={pending} className="min-h-[44px] sm:min-h-0">
      {pending ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" /> : <Search aria-hidden="true" className="mr-2 h-4 w-4" />}
      {pending ? 'Consultando…' : 'Preguntar'}
    </Button>
  );
}

/** Formulario GET del chat de empresa: navegación en cliente con estado de envío visible. */
export default function CompanyChatForm({ ticker, defaultQuestion }: { ticker: string; defaultQuestion?: string }) {
  return (
    <Form action={`/research/${encodeURIComponent(ticker)}#chat-empresa`} className="flex flex-col gap-3 sm:flex-row">
      <input type="hidden" name="view" value="chat" />
      <Input name="chat" defaultValue={defaultQuestion} placeholder={`Pregunta sobre ${ticker} citando fuentes`} minLength={3} required className="h-11 text-base sm:h-9 sm:text-sm" />
      <Submit />
    </Form>
  );
}
