import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const overview = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('F316: la cabecera de Oportunidades DCF envuelve titulo y enlace a 360px', () => {
    // Titulo largo + "Afinar con el Screener" (whitespace-nowrap) en una fila
    // flex sin wrap desbordaban entre 360 y 390px. El título puede llevar
    // as="h2" (jerarquía de encabezados, cccf6f04) sin que el guard se rompa.
    const header = overview.match(
        /<CardHeader className="([^"]*)">\s*<CardTitle (?:as="h2" )?className="text-lg text-gray-100 flex items-center gap-2">\s*<Gem/,
    );
    assert.ok(header, 'cabecera DCF no encontrada');
    assert.match(header[1], /\bflex-wrap\b/);
});
