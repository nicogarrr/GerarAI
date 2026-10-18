import { notFound } from 'next/navigation';
import { looksLikeTicker } from '@/lib/research/ticker-shape';

/** 404 normal solo para rutas que ni parecen un ticker (el guard F286 sigue
 *  prohibiendo 404 en la página para tickers plausibles fuera del master). */
export function assertTickerShape(raw: string): void {
  if (!looksLikeTicker(raw)) notFound();
}
