/** Reserva móvil para llegar al último contenido sin quedar bajo Cerebro/BottomNav. */
export default function PortfolioLayout({ children }: { children: React.ReactNode }) {
  return <div className="pb-[calc(5rem+env(safe-area-inset-bottom))] md:pb-0">{children}</div>;
}
