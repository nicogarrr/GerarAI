
/**
 * Coincidencia del buscador global (Ctrl+K) con las secciones de la app.
 *
 * Antes solo se miraba la etiqueta del destino: escribir "cartera" no
 * encontraba nada porque los items del grupo Cartera se llaman Resumen,
 * Inteligencia, Exposiciones... La promesa del diálogo ("salta a una sección
 * de GerarAI") quedaba incumplida para el propio nombre de la sección. Ahora
 * casa con el título de la sección, la etiqueta del destino y su descripción,
 * sin distinguir tildes ("inversión" encuentra "inversion").
 *
 * Los textos llegan YA RESUELTOS al locale activo (el llamador los traduce
 * con t()): las claves nav.* viven en lib/constants.ts.
 */
export function normalizeNavSearchTerm(text: string): string {
    return text
        .toLocaleLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim();
}

export function navItemMatchesSearch(haystacks: readonly string[], term: string): boolean {
    const needle = normalizeNavSearchTerm(term);
    if (!needle) return true;
    return haystacks.some((hay) => normalizeNavSearchTerm(hay).includes(needle));
}

export function navSectionMatchesSearch(haystacksPorItem: readonly (readonly string[])[], term: string): boolean {
    return haystacksPorItem.some((haystacks) => navItemMatchesSearch(haystacks, term));
}
