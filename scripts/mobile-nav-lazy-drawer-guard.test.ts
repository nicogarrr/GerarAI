/**
 * Guard de bundle: el drawer de la navegación móvil carga diferido
 * (next/dynamic) para que su JS no viaje en el bundle inicial de TODAS las
 * rutas; el gatillo hamburguesa queda eager. El modal nativo conserva
 * aislamiento, foco y Escape sin reconstruirlos en JavaScript.
 * Ejecución: node --experimental-strip-types --test scripts/mobile-nav-lazy-drawer-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const nav = readFileSync('components/MobileNav.tsx', 'utf8');
const drawer = readFileSync('components/MobileNavDrawer.tsx', 'utf8');
// El hook abre el top layer; no debe heredar accidentalmente el trap antiguo.
const drawerBehavior = drawer + readFileSync('hooks/useNativeNavDrawer.ts', 'utf8');

describe('navegación móvil: drawer diferido', () => {
    it('el drawer carga con dynamic() desde el gatillo', () => {
        assert.ok(nav.includes("import('./MobileNavDrawer')"), 'el drawer debe ser un import dinámico');
        assert.ok(!nav.includes('NavItems'), 'el árbol de secciones vive en el drawer, no en el gatillo');
    });

    it('el chunk se precarga al rozar el gatillo (pointerdown/focus)', () => {
        assert.ok(nav.includes('onPointerDown'), 'precarga en pointerdown');
        assert.ok(nav.includes('onFocus'), 'precarga en focus');
    });

    it('MobileNavDrawer importa y ejecuta el hook nativo en su cuerpo', () => {
        // AST, not concatenated text: comments, imports alone, unused helpers
        // and conditional/nested calls cannot stand in for the mounted hook.
        const ast = ts.createSourceFile('MobileNavDrawer.tsx', drawer, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
        const declaration = ast.statements.find((node) =>
            ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)
            && node.moduleSpecifier.text === '@/hooks/useNativeNavDrawer');
        assert.ok(declaration && ts.isImportDeclaration(declaration), 'import del hook nativo ausente');
        const bindings = declaration.importClause?.namedBindings;
        assert.ok(bindings && ts.isNamedImports(bindings) && !declaration.importClause?.isTypeOnly, 'import runtime nombrado del hook ausente');
        const binding = bindings.elements.find((item) => (item.propertyName ?? item.name).text === 'useNativeNavDrawer');
        assert.ok(binding && !binding.isTypeOnly, 'useNativeNavDrawer no importado en runtime');
        const component = ast.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'MobileNavDrawer');
        assert.ok(component && ts.isFunctionDeclaration(component) && component.body, 'componente MobileNavDrawer ausente');
        const returnIndex = component.body.statements.findIndex(ts.isReturnStatement);
        const connected = component.body.statements.some((statement, index) =>
            (returnIndex < 0 || index < returnIndex) &&
            ts.isExpressionStatement(statement) && ts.isCallExpression(statement.expression)
            && ts.isIdentifier(statement.expression.expression)
            && statement.expression.expression.text === binding.name.text
            && statement.expression.arguments.length > 0
            && ts.isObjectLiteralExpression(statement.expression.arguments[0])
            && statement.expression.arguments[0].properties.some((property) =>
                ts.isPropertyAssignment(property) && ts.isIdentifier(property.name)
                && property.name.text === 'active' && property.initializer.kind === ts.SyntaxKind.TrueKeyword));
        assert.ok(connected, 'hook nativo desconectado: falta llamada activa en MobileNavDrawer');
    });

    it('el drawer conserva la gestión de foco, scroll y Escape', () => {
        assert.ok(drawerBehavior.includes("dialog.showModal()"), 'abre el modal nativo');
        assert.ok(!drawerBehavior.includes("document.body.style.overflow ="), 'no modifica el scrollbar raíz');
        assert.ok(drawerBehavior.includes("dialog.addEventListener('close', onNativeClose)"), 'propaga cierre nativo a React');
        assert.ok(!drawerBehavior.includes("document.addEventListener('keydown'"), 'sin trap manual de Escape/Tab');
        assert.ok(drawerBehavior.includes('closeButtonRef.current?.focus()'), 'el foco entra por el botón de cerrar');
        assert.ok(drawer.includes('createPortal'), 'sigue en portal a document.body');
    });
});
