/**
 * Avatares sin foto: iniciales y un color estable derivado del nombre.
 * Mismo nombre, mismo color en cualquier pantalla y en cualquier recarga.
 */

/** Paleta sobria: fondo tenue + texto legible sobre el tema oscuro. */
export const AVATAR_TONES = [
    "bg-sky-400/15 text-sky-300",
    "bg-emerald-400/15 text-emerald-300",
    "bg-violet-400/15 text-violet-300",
    "bg-amber-400/15 text-amber-300",
    "bg-rose-400/15 text-rose-300",
    "bg-teal-400/15 text-teal-300",
    "bg-indigo-400/15 text-indigo-300",
    "bg-fuchsia-400/15 text-fuchsia-300",
] as const;

function hashName(name: string): number {
    const normalized = name.trim().toLowerCase();
    let hash = 5381;
    for (let i = 0; i < normalized.length; i += 1) {
        hash = ((hash << 5) + hash + normalized.charCodeAt(i)) >>> 0;
    }
    return hash;
}

export function avatarTone(name: string): string {
    return AVATAR_TONES[hashName(name) % AVATAR_TONES.length];
}

/** Primera letra o cifra de la palabra: en «(Oakmark)» el "(" no es inicial. */
function firstAlphanumeric(word: string): string | undefined {
    return Array.from(word).find((char) => /[\p{L}\p{N}]/u.test(char));
}

/** Hasta dos iniciales (primera y ultima palabra). Sin nombre: "?" . */
export function avatarInitials(name: string): string {
    const words = name
        .trim()
        .split(/\s+/)
        .filter((word) => /[\p{L}\p{N}]/u.test(word));
    if (words.length === 0) return "?";
    const first = firstAlphanumeric(words[0]) ?? "?";
    const last = words.length > 1 ? (firstAlphanumeric(words[words.length - 1]) ?? "") : "";
    return (first + last).toUpperCase();
}
