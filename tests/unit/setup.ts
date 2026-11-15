// Matchers de DOM (toBeInTheDocument, toHaveTextContent, ...) y limpieza del
// árbol renderizado entre tests.
import '@testing-library/jest-dom/vitest';
import { cleanup, configure } from '@testing-library/react';
import { afterEach } from 'vitest';

// jsdom no implementa layout: estas APIs del navegador no existen y Radix
// (Popover/Select/Dialog) o nuestros componentes las llaman. Se sustituyen por
// no-ops; un test que dependa de geometría real va en e2e/ (Playwright).
if (typeof Element !== 'undefined') {
    Element.prototype.scrollIntoView ??= function scrollIntoView() {};
    Element.prototype.hasPointerCapture ??= function hasPointerCapture() {
        return false;
    };
    Element.prototype.releasePointerCapture ??= function releasePointerCapture() {};
}
if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class ResizeObserver {
        observe() {}
        unobserve() {}
        disconnect() {}
    };
}

// jsdom has no native dialog methods. This shim models only the open flag
// and close event wiring. It does NOT model modal focus, inert, top layer,
// Escape defaults or focus restoration; those require real browser tests.
if (typeof HTMLDialogElement !== 'undefined') {
    HTMLDialogElement.prototype.showModal ??= function showModal() { this.open = true; };
    HTMLDialogElement.prototype.close ??= function close() {
        if (!this.open) return;
        this.open = false;
        this.dispatchEvent(new Event('close'));
    };
}

// findBy*/waitFor esperan 1 s por defecto: con la suite completa en paralelo
// (CPU saturada) un flujo asíncrono de dos pasos tarda más y falla sin ser un
// fallo real. Una aserción que no se cumple sigue fallando; solo se espera más.
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
    cleanup();
});
