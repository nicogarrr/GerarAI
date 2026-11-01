import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const help = readFileSync('components/help/HelpTabs.tsx', 'utf8');

test('F302: la barra de tabs de /help scrollea en horizontal en pantallas estrechas', () => {
    // La barra usa el primitivo Radix (TabsList) en vez de <button> sueltos, asi
    // que ya no hay flex-wrap: el=list scrollea. Medida QA: 413.25px de tabs en
    // un viewport de 390px, sin wrap ni scroller, se salia de la pantalla.
    assert.match(help, /<TabsList[\s\S]*?overflow-x-auto/, 'el TabsList scrollea en horizontal');
    assert.match(help, /<TabsList[\s\S]*?w-max/, 'el TabsList no se encoge, scrollea');
    assert.match(help, /<TabsList[\s\S]*?min-w-full/, 'ocupa todo el ancho disponible en movil');
});

test('F302: la barra de tabs de /help se alcanza con teclado', () => {
    // Con teclado no hay barra de scroll: la region enfocable deja las pestañas
    // alcanzables (WCAG 2.1.1). El nombre accesible no puede ser role="region"
    // porque sobrescribiria el tablist de Radix y su navegacion con flechas.
    assert.match(help, /<TabsList\s+tabIndex=\{0\}/, 'el list es enfocable');
    assert.match(help, /<TabsList[\s\S]*?aria-label=("|\{en \? HELP_EN\.tabsAria : ')/, 'el list tiene nombre accesible');
});

test('F302: la barra de tabs de /help usa el primitivo Tabs de Radix', () => {
    assert.match(
        help,
        /import \{ Tabs, TabsContent, TabsList, TabsTrigger \} from '@\/components\/ui\/tabs';/,
        'importa el primitivo de components/ui/tabs',
    );
    for (const part of ['<Tabs ', '<TabsList', '<TabsTrigger', '<TabsContent']) {
        assert.ok(help.includes(part), `renderiza ${part}`);
    }
    // Sin semantica de pestanas propia: los <button> a mano solo comunicaban la
    // activa por color, y grep role="tablist" no encontraba nada en el repo.
    assert.equal(/<button[\s\S]*?onClick=\{\(\) => setActiveTab/.test(help), false, 'sin boton de tab a mano');
    assert.equal(help.includes('activeTab ==='), false, 'sin estado de tab propio');
});

test('F302: los tres tabs siguen siendo FAQs, Documentacion y Contacto', () => {
    // En inglés (Ajustes → Idioma) la etiqueta sale de HELP_EN; el español sigue en el código.
    for (const [value, label] of [
        ['faq', 'FAQs'],
        ['api', "{en ? HELP_EN.tabDocs : 'Documentación'}"],
        ['community', "{en ? HELP_EN.tabContact : 'Contacto'}"],
    ]) {
        const trigger = help.match(new RegExp(`<TabsTrigger\\s+value="${value}"[\\s\\S]*?>([\\s\\S]*?)</TabsTrigger>`));
        assert.ok(trigger, `hay un TabsTrigger para "${value}"`);
        assert.equal(trigger![1].trim(), label, `la etiqueta de "${value}" es ${label}`);
    }
    const panels = help.match(/<TabsContent /g) ?? [];
    assert.equal(panels.length, 3, 'los tres paneles');
    for (const value of ['faq', 'api', 'community']) {
        assert.ok(help.includes(`<TabsContent value="${value}"`), `panel para "${value}"`);
    }
});

test('F302: los triggers no se encogen ni parten la etiqueta', () => {
    const matches = help.match(/min-h-\[44px\] min-w-fit flex-none snap-start whitespace-nowrap/g) ?? [];
    assert.equal(matches.length, 3, 'los tres tabs llevan objetivo tactil de 44px y etiqueta en una linea');
});
