import type { NextConfig } from "next";

const nextConfig: NextConfig = {
    distDir: process.env.NEXT_DIST_DIR ?? '.next',
    devIndicators: false,
    outputFileTracingIncludes: { '/temas': ['./data/theme-fundamentals/*.json'] },
    /* Performance optimizations */
    compress: true, // Enable gzip compression
    productionBrowserSourceMaps: false, // Disable source maps in production for smaller bundle
    
    // Configuración vacía para Turbopack (Next.js 16+)
    // Necesario para evitar error de build con config webpack legacy
    turbopack: {},
    
    // Optimize images
    images: {
        /*
         * Las miniaturas de noticias llegan de CDNs arbitrarios (Finnhub
         * `banner_image`, Alpha Vantage, NewsAPI `urlToImage`, MarketAux), no de
         * un unico host. Con la lista cerrada en `i.ibb.co` el optimizador
         * respondia 400 y las miniaturas no se veian. `unoptimized` lo ocultaba
         * a costa de servir el original a full resolucion para un thumbnail de
         * 128px: peor LCP y peor CLS de lo que academia.
         *
         * El riesgo SSRF sigue acotado: Next bloquea por defecto las IPs
         * locales y privadas (`images.dangerouslyAllowLocalIP` sigue en false)
         * y limita las redirecciones a 3.
         */
        remotePatterns: [
            {
                protocol: 'https',
                hostname: '**',
                port: '',
                pathname: '/**',
            },
        ],
        formats: ['image/webp', 'image/avif'], // Modern formats for better performance
        deviceSizes: [640, 750, 828, 1080, 1200, 1920, 2048, 3840],
        imageSizes: [16, 32, 48, 64, 96, 128, 256, 384],
    },
    
    // Optimize bundling
    experimental: {
        optimizePackageImports: ['lucide-react', 'recharts'], // Tree-shake large dependencies
        serverActions: {
            // 4mb: Vercel Hobby corta el body de las server actions en ~4.5 MB;
            // un límite mayor solo cambia el error local por un fallo silencioso
            // en producción. La UI avisa al elegir archivos > 4 MB
            // (components/forms/FileUploadInput.tsx).
            bodySizeLimit: '4mb',
        },
    },
    
    typescript: {
        ignoreBuildErrors: false, // Habilitar verificación de TypeScript
    },
    
    // Docker needs standalone output; Vercel packages Next.js itself.
    ...(process.env.VERCEL ? {} : { output: 'standalone' as const }),
    
    // CSP: la fija el middleware (`middleware.ts` + `lib/security/csp.ts`)
    // con un nonce por petición, así `script-src` ya no lleva 'unsafe-inline'
    // en producción. No puede vivir aquí: una cabecera estática no puede
    // noncear los scripts inline de bootstrap/RSC que inyecta Next (sin nonce
    // la app no hidrata), y una CSP aquí SUMARÍA una segunda política a la
    // del middleware (el navegador exige cumplir ambas). 'unsafe-inline' en
    // style-src lo necesitan los estilos inline de React/Tailwind.

    // Headers for better caching and security
    async redirects() {
        return [
            { source: '/research/settings', destination: '/settings', permanent: true },
            { source: '/movers', destination: '/screener?vista=subidas', permanent: true },
            // Carteras se fusiona en Inversores (decisión de Nico, 2026-10-20): la ruta vieja redirige.
            { source: '/inversores/carteras', destination: '/inversores', permanent: true },
            // /inversores/mas-compradas y /inversores/solape pasan a ser vistas
            // de Movimientos 13F (/ownership). Decision de Nico (WhatsApp 2026-10-20 00:59):
            // fusionar las pestañas del hub Inversores/Senales de 10 a 4.
            { source: '/inversores/mas-compradas', destination: '/ownership?vista=mas-compradas', permanent: true },
            { source: '/inversores/solape', destination: '/ownership?vista=solape', permanent: true },
        ];
    },
    async headers() {
        return [
            {
                source: '/:path*',
                headers: [
                    {
                        key: 'X-DNS-Prefetch-Control',
                        value: 'on'
                    },
                    {
                        key: 'X-Frame-Options',
                        value: 'SAMEORIGIN'
                    },
                    {
                        key: 'X-Content-Type-Options',
                        value: 'nosniff'
                    },
                    {
                        key: 'Referrer-Policy',
                        value: 'strict-origin-when-cross-origin'
                    },
                    {
                        key: 'Permissions-Policy',
                        value: 'camera=(), microphone=(), geolocation=()'
                    },
                    {
                        // Aísla el contexto de navegación: una ventana abierta
                        // desde otro origen no conserva window.opener.
                        key: 'Cross-Origin-Opener-Policy',
                        value: 'same-origin'
                    },
                    {
                        key: 'Strict-Transport-Security',
                        value: 'max-age=63072000; includeSubDomains; preload'
                    },
                ],
            },
        ];
    },
};

export default nextConfig;
