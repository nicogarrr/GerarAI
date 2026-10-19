/** Colapso del historial de versiones de tesis: cuando varias versiones
    seguidas traen el MISMO resumen de cambio (p. ej. «Sin cambios materiales
    (±0,5 %)…» cuatro veces), el panel las agrupa en una sola tarjeta con el
    recuento y el rango de versiones. Solo se agrupan entradas con el mismo
    resumen, estado y rating: cualquier diferencia visible rompe el grupo. */
export interface VersionHistoryEntryLike {
  version: number;
  status: string;
  rating: string;
  diff?: { change_summary?: string | null } | null;
}

export function collapseVersionHistory<T extends VersionHistoryEntryLike>(history: T[]): T[][] {
  const groups: T[][] = [];
  for (const entry of history) {
    const summary = (entry.diff?.change_summary ?? '').trim();
    const prev = groups[groups.length - 1];
    const prevFirst = prev?.[0];
    if (
      prev && prevFirst && summary !== ''
      && summary === (prevFirst.diff?.change_summary ?? '').trim()
      && entry.status === prevFirst.status
      && entry.rating === prevFirst.rating
    ) {
      prev.push(entry);
    } else {
      groups.push([entry]);
    }
  }
  return groups;
}
