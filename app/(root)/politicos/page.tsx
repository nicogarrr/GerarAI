import { redirect } from 'next/navigation';

// /politicos era una página aparte (#4756). Nico, 8-nov-2026 16:22: «No hagas
// más pestañas, solo mete lo que aporte valor en cosas ya existentes»: la lista
// vive ahora como sección de /insider (#politicos). Se conserva esta ruta solo
// como redirect para los enlaces viejos, con los mismos filtros.
const KEPT = ['camara', 'partido', 'orden', 'q', 'n'] as const;

export default async function PoliticiansRedirect({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const params = new URLSearchParams();
  for (const key of KEPT) {
    const value = sp[key];
    if (typeof value === 'string' && value) params.set(key, value);
  }
  const qs = params.toString();
  redirect(qs ? `/insider?${qs}#politicos` : '/insider#politicos');
}
