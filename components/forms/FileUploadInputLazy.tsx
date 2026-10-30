'use client';

import dynamic from 'next/dynamic';

import { useT } from '@/lib/i18n/client';

// Frontera cliente para diferir FileUploadInput (procesa imágenes en canvas):
// dynamic() dentro de un componente de servidor no saca el chunk del bundle
// inicial, así que la ficha de research consume esta versión perezosa.
function FileUploadInputLoading() {
  const t = useT();
  return (
    <div role="status" aria-label={t('errors.upload.loading')} className="flex min-h-[44px] items-center rounded-md border border-gray-800 bg-gray-900/40 px-3">
      <span className="block h-3 w-1/4 animate-pulse rounded bg-gray-700/60" aria-hidden="true" />
    </div>
  );
}

export const FileUploadInputLazy = dynamic(() => import('@/components/forms/FileUploadInput').then((m) => m.FileUploadInput), {
  loading: () => <FileUploadInputLoading />,
});
