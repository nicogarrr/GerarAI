import { cache } from 'react';

import { researchRequest } from '@/lib/research/client';

type NewsPreparing = { symbol: string; preparing: boolean };

/**
 * ¿Se están pidiendo ahora las noticias de este ticker recién añadido? Solo lo
 * pregunta la ficha cuando no tiene noticias que enseñar; deduplicado por
 * render (la portada y la sección de noticias comparten la respuesta).
 * Cualquier fallo es «no»: la ficha nunca se queda en «preparando» a ciegas.
 */
export const getNewsPreparing = cache(async (ticker: string): Promise<boolean> => {
  try {
    const data = await researchRequest<NewsPreparing | null>(
      `/api/watchlist/news-preparing/${encodeURIComponent(ticker)}`,
      { fast: true },
    );
    return data?.preparing === true;
  } catch {
    return false;
  }
});
