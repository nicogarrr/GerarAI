'use client';

import { Printer } from 'lucide-react';

/** Imprimir / guardar como PDF desde el navegador (vista de lectura). */
export default function PrintButton() {
  return (
    <button
      type="button"
      onClick={() => window.print()}
      className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-teal-700 hover:text-teal-200 sm:min-h-0"
    >
      <Printer className="h-4 w-4" />Imprimir
    </button>
  );
}
