/** Agrupa las cartas de la biblioteca por autor. Módulo puro, sin imports: se prueba con node:test. */

export type LetterDoc = {
    id: number;
    title: string;
    author: string | null;
    document_type: string;
    source_url: string | null;
    publication_date: string | null;
    status: string;
};

export type AuthorGroup = {
    key: string;
    name: string;
    letters: LetterDoc[];
};

/** Año que aparece escrito en el título ("... 1977", "1s2023", "ago2018"); null si no hay. No es la fecha de publicación. */
export function titleYear(title: string): number | null {
    const matches = title.match(/(?:19|20)\d{2}/g);
    if (!matches) return null;
    return Number(matches[matches.length - 1]);
}

export function authorKey(name: string): string {
    return name
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '');
}

/** Nombre del grupo de cartas sin autor (clave interna; la página lo traduce al pintarlo). */
export const NO_AUTHOR = 'Sin autor';

/** Solo cartas de fondo listas para leer, agrupadas por autor; sin autor van a "Sin autor". Más recientes primero. */
export function groupLetters(docs: LetterDoc[]): AuthorGroup[] {
    const groups = new Map<string, AuthorGroup>();
    for (const doc of docs) {
        if (doc.document_type !== 'fund_letter' || doc.status !== 'ready') continue;
        const name = doc.author?.trim() || NO_AUTHOR;
        const key = authorKey(name) || 'sin-autor';
        const group = groups.get(key) ?? { key, name, letters: [] };
        group.letters.push(doc);
        groups.set(key, group);
    }
    const byRecent = (a: LetterDoc, b: LetterDoc) => {
        const dateA = a.publication_date ?? '';
        const dateB = b.publication_date ?? '';
        if (dateA !== dateB) return dateA < dateB ? 1 : -1;
        const yearA = titleYear(a.title) ?? -1;
        const yearB = titleYear(b.title) ?? -1;
        if (yearA !== yearB) return yearB - yearA;
        return a.title.localeCompare(b.title, 'es');
    };
    const out = [...groups.values()];
    for (const group of out) group.letters.sort(byRecent);
    return out.sort((a, b) => b.letters.length - a.letters.length || a.name.localeCompare(b.name, 'es'));
}

export type LetterNeighbors = { older: LetterDoc | null; newer: LetterDoc | null };

/** Carta anterior (más antigua) y siguiente (más reciente) del mismo autor, en el orden de groupLetters. */
export function letterNeighbors(groups: AuthorGroup[], id: number): LetterNeighbors {
    for (const group of groups) {
        const index = group.letters.findIndex((letter) => letter.id === id);
        if (index === -1) continue;
        return { older: group.letters[index + 1] ?? null, newer: group.letters[index - 1] ?? null };
    }
    return { older: null, newer: null };
}
