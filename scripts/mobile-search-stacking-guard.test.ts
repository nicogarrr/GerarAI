import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const searchCommand = readFileSync('components/SearchCommand.tsx', 'utf8') + readFileSync('components/SearchCommandDialog.tsx', 'utf8');
const mobileNav = readFileSync('components/MobileNav.tsx', 'utf8') + readFileSync('components/MobileNavDrawer.tsx', 'utf8');
const command = readFileSync('components/ui/command.tsx', 'utf8');
const dialog = readFileSync('components/ui/dialog.tsx', 'utf8');

// F356 (reporte de usuario en iPhone, 28/09): en el drawer movil (z-[60]) el
// toque en "Buscar acciones..." no hacia nada visible y los toques caian en
// la app de detras: la paleta (Dialog base z-50) se abria DEBAJO del drawer.
// La paleta de busqueda va a z-[70] en contenido y overlay; el z-50 base del
// resto de dialogs NO se toca (un popover/select dentro de un dialog vive a
// z-50 y quedaria enterrado si se subiera el dialog base).
test('F356: la paleta de busqueda se apila por encima del drawer movil', () => {
    assert.match(mobileNav, /z-\[60\]/, 'el drawer movil sigue en z-[60]');
    assert.match(searchCommand, /className="search-dialog z-\[70\]"/, 'contenido de la paleta a z-[70]');
    assert.match(searchCommand, /overlayClassName="z-\[70\]"/, 'overlay de la paleta a z-[70]');
});

test('F356: la cadena overlayClassName existe (SearchCommand -> CommandDialog -> DialogContent -> DialogOverlay)', () => {
    // Dos aserciones independientes: la ventana de 200 chars entre destructure
    // y tipo se rompio al crecer el bloque de props (onCloseAutoFocus), sin
    // que la cadena dejara de existir.
    assert.match(command, /overlayClassName,\n/);
    assert.match(command, /overlayClassName\?: string/);
    assert.match(command, /overlayClassName=\{overlayClassName\}/);
    assert.match(dialog, /overlayClassName\?: string/);
    assert.match(dialog, /<DialogOverlay className=\{overlayClassName\} \/>/);
});

test('F356: el z-50 base de Dialog no se eleva globalmente', () => {
    const base = dialog.match(/fixed inset-0 z-50 bg-black\/60/g) ?? [];
    assert.equal(base.length, 1, 'el overlay base conserva z-50');
});
