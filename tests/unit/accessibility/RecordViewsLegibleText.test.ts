/**
 * Auditoría 18-nov-2026: etiqueta de columna de RecordViews (tarjetas de
 * registros solo móvil, md:hidden) a 11 px, por debajo del suelo de la casa
 * (text-xs / 12 px, guard legible-text-guard de la auditoría 11-nov).
 * Último texto de lectura bajo 12 px fuera de watchlist (que espera a #5852).
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

function src(path: string): string {
    return readFileSync(join(ROOT, path), 'utf8');
}

describe('RecordViews: etiquetas de columna legibles en móvil', () => {
    it.each(['text-[11px]', 'text-[10px]', 'text-[9px]'])('RecordViews no tiene %s', (cls) => {
        expect(src('components/data/RecordViews.tsx')).not.toContain(cls);
    });

    it('la etiqueta de columna sube a text-xs', () => {
        expect(src('components/data/RecordViews.tsx')).toContain('text-xs uppercase tracking-wide text-gray-500');
    });
});
