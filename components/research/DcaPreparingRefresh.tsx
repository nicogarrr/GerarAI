'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

const EVERY_MS = 15_000;
const MAX_TRIES = 20; // 5 min: después, el aviso se queda y la ficha se recarga a mano

// Un solo temporizador para toda la ficha: con la señal DCA y las noticias
// preparándose a la vez sigue habiendo un refresco cada 15 s, no dos (cada
// router.refresh vuelve a pedir la ficha entera, con todas sus tarjetas).
let mounted = 0;
let timer: ReturnType<typeof setInterval> | null = null;
let tries = 0;
let refresh: (() => void) | null = null;

/** Mientras una tarjeta de la ficha recién encolada se prepara (señal DCA,
    noticias), vuelve a pedir la ficha (server components) cada 15 s; cuando
    llega el dato, la tarjeta lo pinta y deja de montar este componente. */
export default function DcaPreparingRefresh() {
    const router = useRouter();
    useEffect(() => {
        mounted += 1;
        refresh = () => router.refresh();
        if (timer === null && tries < MAX_TRIES) {
            timer = setInterval(() => {
                tries += 1;
                refresh?.();
                if (tries >= MAX_TRIES && timer !== null) {
                    clearInterval(timer);
                    timer = null;
                }
            }, EVERY_MS);
        }
        return () => {
            mounted -= 1;
            if (mounted === 0) {
                if (timer !== null) clearInterval(timer);
                timer = null;
                tries = 0;
                refresh = null;
            }
        };
    }, [router]);
    return null;
}
