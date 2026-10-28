'use client';

import { Printer } from 'lucide-react';

import { Button } from '@/components/ui/button';

/** Imprimir / guardar como PDF desde el navegador (vista de lectura). */
export default function PrintButton() {
  return (
    <Button type="button" variant="outline" size="sm" className="font-medium" onClick={() => window.print()}>
      <Printer aria-hidden="true" className="h-4 w-4" />Imprimir
    </Button>
  );
}
