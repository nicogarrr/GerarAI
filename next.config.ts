import type { NextConfig } from "next";

const nextConfig: NextConfig = {
    distDir: process.env.NEXT_DIST_DIR ?? '.next',
    devIndicators: false,
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
    
    // CSP: en producción sin 'unsafe-eval' (ningún código de la app usa
    // eval/new Function - verificado con grep en app/, components/, lib/,
    // hooks/). En desarrollo se mantiene porque webpack/turbopack usan
    // sourcemaps basados en eval para HMR. 'unsafe-inline' en script-src NO
    // se puede quitar con headers estáticos: Next inyecta scripts inline de
    // bootstrap/RSC; quitarlo exige CSP con nonce vía middleware (trabajo
    // aparte) o la app no hidrata. 'unsafe-inline' en style-src lo necesitan
    // los estilos inline de React/Tailwind.

    // Headers for better caching and security
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
                        key: 'Strict-Transport-Security',
                        value: 'max-age=63072000; includeSubDomains; preload'
                    },
                    {
                        key: 'Content-Security-Policy',
                        value: process.env.NODE_ENV === 'production'
                            ? "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-src https://www.youtube-nocookie.com https://www.youtube.com; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
                            : "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-src https://www.youtube-nocookie.com https://www.youtube.com; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
                    },
                ],
            },
        ];
    },
};

export default nextConfig;
