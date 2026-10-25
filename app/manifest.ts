import type { MetadataRoute } from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: '/',
    name: 'GerarAI — Research OS de inversión',
    short_name: 'GerarAI',
    description: 'Tu memoria de inversor a largo plazo: tesis, alertas y cartera.',
    start_url: '/',
    scope: '/',
    display: 'standalone',
    orientation: 'portrait',
    background_color: '#0a0a0b',
    theme_color: '#0a0a0b',
    lang: 'es',
    dir: 'ltr',
    categories: ['finance', 'business'],
    icons: [
      { src: '/assets/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/assets/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      {
        src: '/assets/icons/icon-maskable-192.png',
        sizes: '192x192',
        type: 'image/png',
        purpose: 'maskable',
      },
      {
        src: '/assets/icons/icon-maskable-512.png',
        sizes: '512x512',
        type: 'image/png',
        purpose: 'maskable',
      },
    ],
    // Sin `screenshots`: las anteriores eran el icono 512 declarado como captura
    // estrecha/ancha (no son capturas). Se añadirán cuando existan reales.
  };
}
