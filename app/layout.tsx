import type { Metadata, Viewport } from "next";
import { Toaster } from "@/components/ui/sonner";
import ServiceWorkerRegister from "@/components/pwa/ServiceWorkerRegister";
import "./globals.css";

export const metadata: Metadata = {
  applicationName: 'GerarAI',
  title: {
    default: "GerarAI - Research OS de inversión fundamental",
    template: "%s | GerarAI"
  },
  description: "GerarAI convierte evidencia, modelos específicos de cada empresa y memoria histórica en tesis fundamentales trazables.",
  keywords: ["fundamental analysis", "investment thesis", "financial modeling", "research OS", "análisis fundamental"],
  authors: [{ name: "GerarAI Team" }],
  creator: "GerarAI",
  icons: {
    icon: [
      { url: '/assets/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/assets/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [{ url: '/assets/icons/apple-touch-icon.png', sizes: '180x180', type: 'image/png' }],
  },
  // Instalable en iPhone: pantalla completa sin chrome de Safari.
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'GerarAI',
  },
  robots: {
    // La app es una herramienta privada: el shell autenticado no debe
    // indexarse. Las unicas paginas publicas (landing, metodologia, ayuda)
    // declaran su propio `robots` para permitirlo.
    index: false,
    follow: false,
  },
  // Sin `alternates.canonical` aqui: un canonico en el layout raiz lo heredan
  // TODAS las rutas, y /metodologia y /help (indexables) pasaban a declarar
  // canonico '/' - se fusionaban con la landing en el indice. Cada pagina
  // publica declara el suyo (la landing ya tenia '/').
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  // La app dibuja bajo el notch/isla dinámica del iPhone (100dvh + safe-area).
  viewportFit: 'cover',
  // Debe coincidir con el fondo real del body (`bg-gray-900` = #0a0a0b en
  // globals.css). Antes decía #101010 y el chrome del móvil se veía distinto
  // del contenido.
  themeColor: '#0a0a0b',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className="dark" suppressHydrationWarning>
      <body className="antialiased" suppressHydrationWarning>
        {children}
        <Toaster />
        {/* Service worker (app shell + fallback offline). Solo en build de
            producción: en dev las cachés del SW estorban al hot-reload. */}
{process.env.NODE_ENV === 'production' ? <ServiceWorkerRegister /> : null}
      </body>
    </html>
  );
}
