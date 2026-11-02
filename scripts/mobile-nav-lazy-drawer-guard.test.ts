/**
 * Guard de bundle: el drawer de la navegación móvil carga diferido
 * (next/dynamic) para que su JS no viaje en el bundle inicial de TODAS las
 * rutas; el gatillo hamburguesa queda eager. El drawer conserva su gestión
 * de foco, Escape, ciclo de Tab y bloqueo de scroll en MobileNavDrawer.
 * Ejecución: node --experimental-strip-types --test scripts/mobile-nav-lazy-drawer-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const nav = readFileSync('components/MobileNav.tsx', 'utf8');
const drawer = readFileSync('components/MobileNavDrawer.tsx', 'utf8');
// El comportamiento del drawer (Escape, Tab, scroll, foco) vive en el hook
// compartido con PublicMobileNav desde la consolidación de los dos drawers.
const drawerBehavior = drawer + readFileSync('hooks/useNavDrawer.ts', 'utf8');

describe('navegación móvil: drawer diferido', () => {
    it('el drawer carga con dynamic() desde el gatillo', () => {
        assert.ok(nav.includes("import('./MobileNavDrawer')"), 'el drawer debe ser un import dinámico');
        assert.ok(!nav.includes('NavItems'), 'el árbol de secciones vive en el drawer, no en el gatillo');
    });

    it('el chunk se precarga al rozar el gatillo (pointerdown/focus)', () => {
        assert.ok(nav.includes('onPointerDown'), 'precarga en pointerdown');
        assert.ok(nav.includes('onFocus'), 'precarga en focus');
    });

    it('el drawer conserva la gestión de foco, scroll y Escape', () => {
        assert.ok(drawerBehavior.includes("document.body.style.overflow = 'hidden'"), 'bloquea el scroll del body al abrir');
        assert.ok(drawerBehavior.includes("e.key === 'Escape'"), 'Escape cierra');
        assert.ok(drawerBehavior.includes('closeButtonRef.current?.focus()'), 'el foco entra por el botón de cerrar');
        assert.ok(drawer.includes('createPortal'), 'sigue en portal a document.body');
    });
});
