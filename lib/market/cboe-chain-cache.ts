/**
 * Instancia COMPARTIDA de la caché dedupe de cadenas de opciones de CBOE
 * (lib/market/cboe-options.ts). La cadena de un subyacente es pesada
 * (~0,5 MB): una sola instancia sirve a la valoración de la cuenta demo
 * (manual-demo.actions.ts) y al selector guiado del ticket
 * (demo-option-chain.actions.ts), así dos consumidores del mismo subyacente
 * en la misma ventana de 60 s hacen UN solo fetch a la fuente.
 *
 * Cada instancia serverless lleva la suya (no es protección global de
 * cuota): la disciplina anti-estampida (TTL, máx. inflight, backoff con
 * Retry-After) vive en createCboeChainCache.
 */
import { createCboeChainCache } from '@/lib/market/cboe-options';

export const sharedCboeChainCache = createCboeChainCache();
