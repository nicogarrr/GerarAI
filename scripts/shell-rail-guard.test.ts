import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
describe('navegación compacta', () => {
    it('barra de iconos por defecto, conserva la elección de expandir', () => {
        assert.match(readFileSync('lib/ui/sidebar-preference.ts', 'utf8'), /SIDEBAR_COLLAPSED_COOKIE = 'cavaai-sidebar-collapsed'/);
        const layout = readFileSync('app/(root)/layout.tsx', 'utf8');
        assert.match(layout, /import \{ SIDEBAR_COLLAPSED_COOKIE \} from [\"']@\/lib\/ui\/sidebar-preference[\"']/);
        assert.doesNotMatch(layout, /import Sidebar, \{/);
        // Cookie ausente = expandido (primera visita). Solo '1' pliega.
        assert.match(readFileSync('app/(root)/layout.tsx', 'utf8'), /jar.get\(SIDEBAR_COLLAPSED_COOKIE\)\?\.value === '1'/);
    });
    it('móvil mantiene Cartera activa en sus subrutas sin alterar desktop', () => {
        const src = readFileSync('components/layout/BottomNav.tsx', 'utf8');
        assert.match(src, /isNavItemActive\(pathname, item.href\)/);
        const active = (path: string, href: string) => path === href || path.startsWith(`${href}/`);
        assert.equal(active('/portfolio/intelligence', '/portfolio'), true);
        assert.equal(active('/portfolio-copy', '/portfolio'), false);
        assert.equal(active('/research/assistant', '/research/assistant'), true);
    });
    it('lista de canales sin promesas obsoletas ni texto de relleno', () => {
        const src = readFileSync('app/(root)/inversores/canales/page.tsx', 'utf8');
        assert.doesNotMatch(src, /sin avatares copiados|sin vídeos|section.hint/);
        assert.match(src, /channel.source/);
    });
});
