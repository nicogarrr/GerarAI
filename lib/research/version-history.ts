/** Colapso del historial de versiones de tesis: cuando varias versiones
    seguidas traen el MISMO resumen de cambio (p. ej. «Sin cambios materiales
    (±0,5 %)…» cuatro veces), el panel las agrupa en una sola tarjeta con el
    recuento y el rango de versiones. Solo se agrupan entradas con el mismo
    resumen, estado y rating: cualquier diferencia visible rompe el grupo. */
export interface VersionHistoryEntryLike {
  version: number;
  status: string;
  rating: string;
  diff?: { change_summary?: string | null; rating_changed?: boolean } | null;
}

export type VersionHistoryBadge = {
  key: 'status' | 'rating' | 'rating-change';
  text: string;
};

/**
 * Badges de una tarjeta de versión sin repetir el mismo texto. `status` y
 * `rating` son ejes distintos, pero sus etiquetas pueden coincidir (p. ej.
 * «datos insuficientes» en ambos): en ese caso se pinta uno solo. Cuando el
 * rating sí aporta, se rotula para no confundirlo con el estado.
 */
export function versionHistoryBadges(
  entry: Pick<VersionHistoryEntryLike, 'status' | 'rating' | 'diff'>,
  translate: (value: string) => string,
): VersionHistoryBadge[] {
  const status = translate(entry.status);
  const rating = translate(entry.rating);
  const badges: VersionHistoryBadge[] = [{ key: 'status', text: status }];
  if (rating && rating !== status) {
    badges.push({ key: 'rating', text: `rating: ${rating}` });
  }
  if (entry.diff?.rating_changed) {
    badges.push({ key: 'rating-change', text: 'rating cambiado' });
  }
  return badges;
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
