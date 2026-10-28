'use client';

import dynamic from 'next/dynamic';

// Frontera cliente para diferir FileUploadInput (procesa imágenes en canvas):
// dynamic() dentro de un componente de servidor no saca el chunk del bundle
// inicial, así que la ficha de research consume esta versión perezosa.
export const FileUploadInputLazy = dynamic(() => import('@/components/forms/FileUploadInput').then((m) => m.FileUploadInput), {
  loading: () => (
    <div role="status" aria-label="Cargando el selector de archivo" className="flex min-h-[44px] items-center rounded-md border border-gray-800 bg-gray-900/40 px-3">
      <span className="block h-3 w-1/4 animate-pulse rounded bg-gray-700/60" aria-hidden="true" />
    </div>
  ),
});
