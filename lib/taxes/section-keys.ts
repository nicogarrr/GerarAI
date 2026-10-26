/** Claves de las secciones hijas de una declaración: el año solo no basta
 *  porque dos componentes distintos comparten el mismo ejercicio. */
export type FilingChildSection = 'tme-preview' | 'sale-casillas';

export function filingSectionKey(kind: FilingChildSection, year: number): string {
  return `${kind}-${year}`;
}
