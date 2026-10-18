import Link from 'next/link';
import type { Metadata } from 'next';
import { GerarAIWordmark } from '@/components/GerarAIWordmark';

export const metadata: Metadata = { title: 'Página no encontrada' };

export default function NotFound() {
  return (
    <div className="min-h-dvh text-gray-300">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 px-4 py-3">
        <Link href="/inicio" className="inline-flex min-h-11 items-center" aria-label="GerarAI, inicio"><GerarAIWordmark /></Link>
        <nav aria-label="Navegación principal" className="flex flex-wrap gap-4">
          <Link className="inline-flex min-h-11 items-center" href="/inicio">Inicio</Link>
          <Link className="inline-flex min-h-11 items-center" href="/discover">Descubrir</Link>
          <Link className="inline-flex min-h-11 items-center" href="/watchlist">Watchlist</Link>
        </nav>
      </header>
    <main id="content" tabIndex={-1} className="mx-auto flex min-h-[60vh] w-full max-w-2xl flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <p className="text-sm font-semibold tracking-widest text-teal-300 uppercase">Error 404</p>
      <h1 className="text-3xl font-bold text-gray-100">Página no encontrada</h1>
      <p className="max-w-md text-sm leading-6 text-gray-400">
        La página que buscas no existe o se ha movido. Revisa la dirección o vuelve a empezar desde un lugar
        que conozcas.
      </p>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-3">
        <Link
          href="/inicio"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-teal-400 px-5 text-sm font-semibold text-gray-950 transition-colors hover:bg-teal-300"
        >
          Volver al inicio
        </Link>
        <Link
          href="/watchlist"
          className="inline-flex min-h-[44px] items-center justify-center rounded-lg border border-gray-700 px-5 text-sm text-gray-200 transition-colors hover:bg-gray-800"
        >
          Ir a la watchlist
        </Link>
      </div>
    </main>
    </div>
  );
}
