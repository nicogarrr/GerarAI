'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

const EVERY_MS = 15_000;
const MAX_TRIES = 20; // 5 min: después, el aviso se queda y la ficha se recarga a mano

/** Mientras la señal DCA recién encolada se evalúa, vuelve a pedir la ficha
    (server components) cada 15 s; cuando llega, la sección pinta la tarjeta. */
export default function DcaPreparingRefresh() {
    const router = useRouter();
    useEffect(() => {
        let tries = 0;
        const id = setInterval(() => {
            tries += 1;
            router.refresh();
            if (tries >= MAX_TRIES) clearInterval(id);
        }, EVERY_MS);
        return () => clearInterval(id);
    }, [router]);
    return null;
}
