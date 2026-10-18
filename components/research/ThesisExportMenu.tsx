"use client";

import { BookOpen, FileDown, FileText } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Salidas de la tesis: leerla bien (pagina dedicada imprimible) y
 * descargarla en PDF o Markdown de la version PUBLICADA. El vault Obsidian
 * completo sigue en /export; Journal y EPUB salen del menu (apenas se usan).
 */
export default function ThesisExportMenu({ ticker }: { ticker: string }) {
  const encoded = encodeURIComponent(ticker);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-gray-700 px-4 py-2 text-sm font-medium text-gray-200 transition hover:border-teal-700 hover:text-teal-200 sm:min-h-0">
        <FileDown className="h-4 w-4" />
        Leer / Descargar
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem asChild className="min-h-[44px] sm:min-h-0">
          <a href={`/research/${encoded}/tesis`}>
            <BookOpen className="mr-2 h-4 w-4" />
            Leer la tesis
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem asChild className="min-h-[44px] sm:min-h-0">
          <a href={`/api/thesis/${encoded}/pdf`} download>
            <FileDown className="mr-2 h-4 w-4" />
            Descargar PDF
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem asChild className="min-h-[44px] sm:min-h-0">
          <a href={`/api/thesis-memo/${encoded}`} download>
            <FileText className="mr-2 h-4 w-4" />
            Descargar Markdown
          </a>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
