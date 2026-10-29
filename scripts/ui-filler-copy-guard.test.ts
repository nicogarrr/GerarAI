import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
test('obvious page descriptions do not come back as filler',()=>{
 const sources=['app/(root)/research/page.tsx','app/(root)/discover/page.tsx','app/(root)/screeners/page.tsx','app/(root)/watchlist/page.tsx','components/portfolio/PortfolioTabs.tsx'].map(p=>readFileSync(p,'utf8')).join('\n');
 assert.doesNotMatch(sources,/Encuentra empresas para estudiar|Construye fórmulas seguras|Seguimiento detallado de valoración|Seguimiento de tus inversiones|Cada ficha agrupa su análisis en seis etapas/);
 // La cabecera no repite la advertencia genérica; la procedencia se conserva en los datos.
 assert.doesNotMatch(readFileSync('components/portfolio/PortfolioTabs.tsx','utf8'),/Yahoo Finance|~15 min de retardo/);
 assert.match(readFileSync('app/(root)/watchlist/page.tsx','utf8'),/watchlist-unavailable/);
});
