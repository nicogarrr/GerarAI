import type { Metadata, Viewport } from "next";
import { Toaster } from "@/components/ui/sonner";
import ServiceWorkerRegister from "@/components/pwa/ServiceWorkerRegister";
import { LocaleProvider } from "@/lib/i18n/client";
import { getLocale, getT } from "@/lib/i18n/server";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  // Título y descripciones en el idioma elegido (cookie); el español es el predeterminado.
  const [t, locale] = await Promise.all([getT(), getLocale()]);
  return {
  applicationName: 'GerarAI',
  title: {
    default: t('shell.meta.title'),
    template: "%s | GerarAI"
  },
  description: t('shell.meta.description'),
  metadataBase: new URL('https://gerarai.vercel.app'),
  openGraph: {
    siteName: 'GerarAI',
    title: t('shell.meta.title'),
    description: t('shell.meta.shareDescription'),
    locale: locale === 'en' ? 'en_US' : 'es_ES',
    type: 'website',
    images: [{ url: '/assets/og/cover.png', width: 1200, height: 630, alt: 'GerarAI' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: t('shell.meta.title'),
    description: t('shell.meta.shareDescription'),
    images: ['/assets/og/cover.png'],
  },
  keywords: ["fundamental analysis", "investment thesis", "financial modeling", "research OS", t('shell.meta.keywordFundamental')],
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
}

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
  // Mismo tema que `color-scheme: dark` en globals.css, ya en el <head>:
  // el navegador no pinta un primer fotograma de controles claros.
  colorScheme: 'dark',
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Idioma de la interfaz: cookie `gerarai_locale` (selector en Ajustes),
  // español por defecto. Leerla aquí hace dinámicas las rutas: el copy ya
  // depende de la request.
  const locale = await getLocale();
  return (
    <html lang={locale} className="dark" suppressHydrationWarning>
      <body className="antialiased" suppressHydrationWarning>
        <LocaleProvider locale={locale}>{children}</LocaleProvider>
        <Toaster />
        {/* Service worker (app shell + fallback offline). Solo en build de
            producción: en dev las cachés del SW estorban al hot-reload. */}
{process.env.NODE_ENV === 'production' ? <ServiceWorkerRegister /> : null}
      </body>
    </html>
  );
}
