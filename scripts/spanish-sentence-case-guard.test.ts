/**
 * Guard: los textos de la interfaz en es-ES van en mayúscula de frase.
 *
 * En español solo se escribe con mayúscula la primera palabra de un título,
 * botón o etiqueta (y los nombres propios): «Nueva alerta», «Guardar cambios»,
 * no «Nueva Alerta» ni «Guardar Cambios» (calco del Title Case inglés). Los
 * diálogos de alertas e inversiones lo mezclaban.
 *
 * El guard busca una palabra de interfaz habitual al inicio (Nueva, Crear,
 * Guardar, Tipo…) seguida de otra palabra con mayúscula que no sea un nombre
 * propio conocido (Cerebro, Obsidian, ProPicks, secciones de la app…). Las
 * líneas de comentario no cuentan.
 *
 * Ejecución: node --experimental-strip-types --test scripts/spanish-sentence-case-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const STARTERS = [
    'Nueva', 'Nuevo', 'Crear', 'Guardar', 'Buscar', 'Editar', 'Eliminar', 'Borrar', 'Tipo',
    'Añadir', 'Agregar', 'Aplicar', 'Cantidad', 'Todos', 'Todas', 'Centro', 'Preguntas',
    'Posiciones', 'Tu', 'Tus', 'Mi', 'Mis', 'Valor', 'Escenario', 'Configurar', 'Registrar',
    'Importar', 'Exportar', 'Seleccionar', 'Gestionar', 'Resumen', 'Detalles', 'Datos',
    'Precio', 'Fecha', 'Comisión', 'Lista', 'Filtros', 'Limpiar', 'Cancelar', 'Confirmar',
];
const CONNECTORS = ['de', 'del', 'la', 'el', 'los', 'las', 'y', 'en', 'a', 'para', 'por', 'con', 'sin', 'al'];
/** Nombres propios, marcas y secciones de la app que sí llevan mayúscula. */
const PROPER = new Set([
    'Cerebro', 'Obsidian', 'Markdown', 'ProPicks', 'Pro', 'Inversores', 'Movimientos', 'Posiciones',
    'Análisis', 'Aprender', 'Research', 'Telegram', 'Google', 'Apple', 'Outlook', 'Yahoo',
    'GerarAI', 'IBKR', 'Flex', 'Piotroski', 'Altman', 'Sharpe', 'Pearson', 'Brier', 'YouTube',
    'Inicio', 'Bear', 'Bull', 'Brent', 'España', 'Nasdaq', 'Wall', 'Fórmula', 'Nico', 'Biblioteca',
    'Fiscalidad', 'Hacienda', 'Renta', 'Modelo', 'Interactive', 'Brokers', 'DCA',
]);

const TITLE_CASE = new RegExp(
    `(?<![\\p{L}\\p{N}_.-])(${STARTERS.join('|')})(?: (?:${CONNECTORS.join('|')}))? (\\p{Lu}\\p{Ll}+)(?![\\p{L}])`,
    'gu',
);

const ROOTS = ['app', 'components', 'lib', 'hooks'];
const SKIP = /(\.test\.|__tests__|\.d\.ts$|openapi\.generated\.ts$)/;

function listSources(dir: string): string[] {
    const out: string[] = [];
    for (const name of readdirSync(dir)) {
        if (name === 'node_modules' || name.startsWith('.')) continue;
        const path = join(dir, name);
        if (statSync(path).isDirectory()) out.push(...listSources(path));
        else if (/\.(tsx?|json)$/.test(name) && !SKIP.test(path)) out.push(path);
    }
    return out;
}

function isComment(line: string): boolean {
    const t = line.trim();
    return t.startsWith('//') || t.startsWith('*') || t.startsWith('/*') || t.startsWith('{/*');
}

export function findTitleCase(text: string): string[] {
    const hits: string[] = [];
    for (const m of text.matchAll(TITLE_CASE)) {
        if (!PROPER.has(m[2])) hits.push(m[0]);
    }
    return hits;
}

describe('textos es-ES en mayúscula de frase', () => {
    it('detecta el calco inglés y respeta los nombres propios', () => {
        assert.deepEqual(findTitleCase('<DialogTitle>Nueva Alerta</DialogTitle>'), ['Nueva Alerta']);
        assert.deepEqual(findTitleCase("label: 'Tipo de Operación'"), ['Tipo de Operación']);
        assert.deepEqual(findTitleCase('Nueva alerta · Tipo de operación · Guardar cambios'), []);
        assert.deepEqual(findTitleCase('Preguntar al Cerebro · Descargar para Obsidian · Volver a Análisis'), []);
        assert.deepEqual(findTitleCase('Mitad Superior'), []);
    });

    it('ningún texto de la app usa Title Case inglés', () => {
        const offenders: string[] = [];
        for (const root of ROOTS) {
            for (const file of listSources(root)) {
                const lines = readFileSync(file, 'utf8').split('\n');
                lines.forEach((line, i) => {
                    if (isComment(line)) return;
                    for (const hit of findTitleCase(line)) offenders.push(`${file}:${i + 1} «${hit}»`);
                });
            }
        }
        assert.deepEqual(offenders, [], `Usa mayúscula de frase («Nueva alerta», no «Nueva Alerta»):\n${offenders.join('\n')}`);
    });
});
