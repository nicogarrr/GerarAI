// Shim de @/lib/i18n/server para la guarda de frontera de sesión: traduce con
// los diccionarios ES reales, sin next/headers ni cookies.
import { readFileSync } from 'node:fs';

const flatten = (tree, prefix, out) => {
    for (const [key, value] of Object.entries(tree)) {
        const path = prefix ? `${prefix}.${key}` : key;
        if (typeof value === 'string') out[path] = value;
        else if (value && typeof value === 'object') flatten(value, path, out);
    }
};

const messages = {};
for (const area of ['errors', 'auth', 'landing', 'emails']) {
    const tree = JSON.parse(readFileSync(new URL(`../lib/i18n/messages/es/${area}.json`, import.meta.url), 'utf8'));
    flatten(tree, area, messages);
}

export async function getLocale() {
    return 'es';
}

export async function getT() {
    return (key, vars) => {
        let value = messages[key] ?? key;
        if (vars) value = value.replace(/\{(\w+)\}/g, (match, name) => String(vars[name] ?? match));
        return value;
    };
}
