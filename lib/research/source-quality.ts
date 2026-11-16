/** Keep the existing unofficial-data warning without displaying provider names. */
export function isUnofficialSource(source: string | null | undefined): boolean {
  return source?.trim().toLowerCase() === 'yahoo_fundamentals';
}
