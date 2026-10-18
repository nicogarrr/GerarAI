'use client';

import { useEffect } from 'react';

/** Lleva al usuario al panel de la vista activa: la cabecera de la ficha ocupa más de una pantalla. */
export default function ScrollToOnMount({ targetId }: { targetId: string }) {
  useEffect(() => {
    document.getElementById(targetId)?.scrollIntoView({ block: 'start' });
  }, [targetId]);
  return null;
}
