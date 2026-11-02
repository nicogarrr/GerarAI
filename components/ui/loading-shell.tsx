/**
 * Shell accesible de los esqueletos de ruta (los loading.tsx de app/(root)): el
 * <main> con salto al contenido y aria-busy, el aviso sr-only con
 * role="status" traducido y el wrapper aria-hidden que oculta el esqueleto a
 * lectores de pantalla. Cada ruta pasa solo su esqueleto y sus clases; la
 * regla de accesibilidad vive una sola vez. `label` viene de
 * ti('common.states.loading') en la ruta (getT es async: la espera queda en
 * el loading.tsx, que ya es async por contrato de Next).
 */
export function LoadingShell({
  label,
  className,
  contentClassName,
  children,
}: {
  label: string;
  className: string;
  contentClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <main id="content" tabIndex={-1} aria-busy="true" className={className}>
      <span className="sr-only" role="status">{label}</span>
      <div aria-hidden="true" className={contentClassName}>{children}</div>
    </main>
  );
}
