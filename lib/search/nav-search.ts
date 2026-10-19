import type { NavItem, NavSection } from '@/lib/constants';

/**
 * Coincidencia del buscador global (Ctrl+K) con las secciones de la app.
 *
 * Antes solo se miraba `item.label`: escribir "cartera" no encontraba nada
 * porque los items del grupo Cartera se llaman Resumen, Inteligencia,
 * Exposiciones... La promesa del diálogo ("salta a una sección de GerarAI")
 * quedaba incumplida para el propio nombre de la sección. Ahora casa con el
 * título de la sección, la etiqueta del destino y su descripción, sin
 * distinguir tildes ("inversión" encuentra "inversion").
 */
export function normalizeNavSearchTerm(text: string): string {
    return text
        .toLocaleLowerCase()
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .trim();
}

export function navItemMatchesSearch(section: NavSection, item: NavItem, term: string): boolean {
    const needle = normalizeNavSearchTerm(term);
    if (!needle) return true;
    const haystacks = [section.title, item.label, item.subnavLabel ?? '', item.description ?? ''];
    return haystacks.some((hay) => normalizeNavSearchTerm(hay).includes(needle));
}

export function navSectionMatchesSearch(section: NavSection, term: string, flatten: (sections: NavSection[]) => NavItem[]): boolean {
    return flatten([section]).some((item) => navItemMatchesSearch(section, item, term));
}
