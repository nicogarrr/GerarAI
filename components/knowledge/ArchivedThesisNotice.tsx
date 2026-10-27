/** Context around an immutable archive, never a rewrite of its contents. */
export function ArchivedThesisNotice({ documentType }: { documentType: string }) {
  if (documentType !== 'own_thesis') return null;
  return (
    <aside className="mb-4 rounded-lg border border-amber-900/60 bg-amber-950/20 p-3 text-sm leading-6 text-amber-200" role="note">
      Tesis archivada: se conserva el texto original de esa versión, no una valoración actual.
      Los porcentajes de margen sin fórmula explícita en el documento tienen una convención no verificada:
      no los compares con el margen actual (V - P) / V ni los uses como señal actual.
    </aside>
  );
}
