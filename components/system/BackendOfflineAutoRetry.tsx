'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

/** Ventana típica de un restart del backend: 10-20 s (observado en prod).
 *  Cuatro reintentos con espera creciente la cruzan sin martillear. */
const RETRY_DELAYS_MS = [5000, 10000, 20000, 40000];

/**
 * Reintento automático del estado «motor desconectado»: el fallo casi
 * siempre es transitorio (restart del backend, 502 de unos segundos) y la
 * pantalla debe recuperarse sola sin exigir al usuario pulsar Reintentar.
 * `router.refresh()` repite el render en servidor; si el motor ya responde,
 * la página vuelve con datos y este componente se desmonta.
 */
export function BackendOfflineAutoRetry() {
  const router = useRouter();
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (attempt >= RETRY_DELAYS_MS.length) return;
    const timer = setTimeout(() => {
      setAttempt((value) => value + 1);
      router.refresh();
    }, RETRY_DELAYS_MS[attempt]);
    return () => clearTimeout(timer);
  }, [attempt, router]);

  if (attempt >= RETRY_DELAYS_MS.length) return null;
  return (
    <p className="text-xs text-teal-300/80" role="status">
      Reintentando automáticamente (intento {attempt + 1} de {RETRY_DELAYS_MS.length})…
    </p>
  );
}
