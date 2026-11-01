import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
test('video empty states explain verified coverage and offer existing routes',()=>{
 const src=readFileSync('app/(root)/inversores/_components/InvestorVideos.tsx','utf8')+readFileSync('lib/i18n/messages/es/investors.json', 'utf8');
 assert.match(src,/validInvestorVideos\(videos\)/);
 assert.match(src,/No hay vídeos verificados disponibles/);
 // cartas son de cada ficha, no enviar a un índice genérico.
 for(const route of ['/inversores/canales']) assert.ok(src.includes(`href="${route}"`));
 assert.doesNotMatch(src,/>Sin datos</);
 const page=readFileSync('app/(root)/inversores/videos/page.tsx','utf8')+readFileSync('lib/i18n/messages/es/investors.json', 'utf8');
 assert.match(page,/Volver a la lista de inversores/);
});
