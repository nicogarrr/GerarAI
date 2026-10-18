/**
 * D2c: ningun 'use client' sin motivo.
 *
 * Por que un guard y no una nota en el README: cada 'use client' es un modulo
 * de JS que el navegador descarga, parsea y ejecuta para pintar algo que el
 * servidor ya sabe pintar. Cuando la directiva no esta justificada, ese JS es
 * gasto invisible, y a los tres meses ya nadie recuerda por que estaba. Un
 * guard lo convierte en un fallo de CI en vez de en una opinion.
 *
 * Que mira: un fichero de `components/` o `app/` con la directiva en el
 * prologo tiene que emitir AL MENOS una senal de cliente:
 *   - un hook de cliente (useState/useEffect/useReducer/useRef/useContext/
 *     useTransition/..., los de `next/navigation` y los de `react-dom`);
 *   - un event handler JSX (onClick, onChange, onSubmit, ...);
 *   - acceso a window/document/localStorage/navigator/...;
 *   - `dynamic(..., { ssr: false })`, `lazy` o `createContext`;
 *   - un paquete que solo funciona en cliente (@radix-ui/*, recharts, cmdk,
 *     sonner, react-hook-form, ...);
 *   - o importar un modulo que ya es cliente (sin la directiva, el import
 *     revienta).
 *
 * Lo que NO cuenta como motivo, y por eso hay una lista de excepciones: que
 * el fichero lo importe un Client Component. En ese caso sigue siendo cliente
 * por herencia, asi que quitar la directiva no ahorra un solo byte y solo
 * anade ruido al diff. Esa es la UNICA categoria con excepciones, y cada
 * entrada lleva escrito por que sigue asi.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/no-useless-use-client.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { tmpdir } from 'node:os';
import { analyzeSource, auditRepo, auditUseClient } from './use-client-audit.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

/**
 * Excepciones de `components/`.
 *
 * Unico motivo admitido: el fichero lo importa un Client Component, asi que
 * ya es cliente por herencia y la directiva es redundante pero inocua. No se
 * tocan porque convertirlos no ahorra bytes: son hoja del subarbol cliente de
 * PortfolioTabs / ProPicksTabs / TaxesView.
 */
const COMPONENTS_EXCEPTIONS: Record<string, string> = {
  'components/portfolio/PortfolioScores.tsx':
    "Lo importa components/portfolio/PortfolioTabs.tsx ('use client'), asi que ya viaja en el paquete del cliente por herencia. Quitar la directiva NO ahorra un byte (sigue siendo cliente) y solo anade ruido al diff. Sin senal propia de cliente: solo pinta datos que recibe por props.",
  'components/portfolio/PortfolioSummary.tsx':
    "Lo importa components/portfolio/PortfolioTabs.tsx ('use client'): cliente por herencia, quitar la directiva no ahorra un byte. Se deja tal cual para no ensuciar el diff de un fichero sin ganancia real.",
  'components/portfolio/PortfolioTearsheet.tsx':
    "Lo importa components/portfolio/PortfolioTabs.tsx ('use client'): cliente por herencia, quitar la directiva no ahorra un byte. Se deja tal cual para no ensuciar el diff de un fichero sin ganancia real.",
  'components/proPicks/StrategyFactsheet.tsx':
    "Lo importa components/proPicks/ProPicksTabs.tsx ('use client'): cliente por herencia, quitar la directiva no ahorra un byte. Se deja tal cual para no ensuciar el diff de un fichero sin ganancia real.",
  'components/proPicks/WalkForwardResults.tsx':
    "Lo importa components/proPicks/ProPicksTabs.tsx ('use client'): cliente por herencia, quitar la directiva no ahorra un byte. Se deja tal cual para no ensuciar el diff de un fichero sin ganancia real.",
};

/**
 * Excepciones de `app/`.
 *
 * Vacia a proposito: los cuatro ficheros de `app/` con la directiva
 * (sign-in/page, error, global-error, ownership/SyncButton) la necesitan de
 * verdad (useState/useEffect/useTransition + handlers de submit), asi que el
 * mismo guard pasa sin excepciones. Se deja la lista declarada para que anadir
 * una excepcion aqui sea un acto explicito y no un descuido.
 */
const APP_EXCEPTIONS: Record<string, string> = {};

const audit = auditRepo(root, ['components', 'app', 'hooks', 'lib']);
const byRel = new Map(audit.map((r) => [r.rel, r]));

function unjustified(subdir: string, exceptions: Record<string, string>): string[] {
  return audit
    .filter((r) => r.hasUseClient && r.rel.startsWith(`${subdir}/`) && !r.justified)
    .map((r) => r.rel)
    .filter((rel) => !(rel in exceptions))
    .sort();
}

describe("'use client' justificado o inexistente", () => {
  it('ningún fichero de components/ lo usa sin motivo', () => {
    assert.deepEqual(unjustified('components', COMPONENTS_EXCEPTIONS), []);
  });

  it('ningún fichero de app/ lo usa sin motivo', () => {
    assert.deepEqual(unjustified('app', APP_EXCEPTIONS), []);
  });

  it('ningún fichero de hooks/ o lib/ lo usa sin motivo', () => {
    const offenders = audit
      .filter((r) => r.hasUseClient && (r.rel.startsWith('hooks/') || r.rel.startsWith('lib/')) && !r.justified)
      .map((r) => r.rel)
      .sort();
    assert.deepEqual(offenders, []);
  });
});

describe('el guard muerde de verdad (casos negativos)', () => {
  // Un guard que no puede fallar no es un guard. Se escriben ficheros REALES
  // en un temporal y se les pasa el MISMO codigo que recorre el repo, para
  // que lo que se demuestra es el caminho de ejecucion del guard, no una
  // funcion auxiliar del test.

  function auditTemp(files: Record<string, string>) {
    const dir = mkdtempSync(join(tmpdir(), 'd2c-use-client-'));
    try {
      for (const [rel, body] of Object.entries(files)) {
        const full = join(dir, rel);
        mkdirSync(dirname(full), { recursive: true });
        writeFileSync(full, body, 'utf8');
      }
      return auditRepo(dir, ['.']);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }

  it('detecta un componente estatico con la directiva puesta', () => {
    // El caso real de D2c: HTML puro, ni un hook, ni un handler, y aun asi
    // el navegador recibe un modulo de JS para pintarlo.
    const rows = auditTemp({
      'components/Thing.tsx': `'use client';

export function Thing({ label }: { label: string }) {
  return <div className="p-2">{label}</div>;
}
`,
    });
    const row = rows.find((r) => r.rel === 'components/Thing.tsx');
    assert.ok(row, 'el auditor no encontro el temporal');
    assert.equal(row.hasUseClient, true);
    assert.equal(row.justified, false, 'una directiva muerta debe marcarse como injustificada');
  });

  it('detecta la directiva muerta aunque el fichero use useMemo y useCallback', () => {
    // useMemo/useCallback se ejecutan en el render del servidor: no obligan a
    // la directiva. Sirven de caso negativo contra el atajo de "usa un hook,
    // luego es cliente".
    const rows = auditTemp({
      'components/MemoThing.tsx': `'use client';

import { useCallback, useMemo } from 'react';

const list = [1, 2, 3];

export function MemoThing() {
  const total = useMemo(() => list.reduce((a, b) => a + b, 0), []);
  const label = useCallback(() => String(total), [total]);
  return <p>{label()}</p>;
}
`,
    });
    const row = rows.find((r) => r.rel === 'components/MemoThing.tsx');
    assert.equal(row?.justified, false, 'useMemo/useCallback no justifican la directiva');
  });

  it('detecta la directiva muerta en un archivo de app/ con la misma regla', () => {
    const rows = auditTemp({
      'app/(root)/algo/page.tsx': `'use client';

export default function Page() {
  return <main className="p-4">hola</main>;
}
`,
    });
    const row = rows.find((r) => r.rel === 'app/(root)/algo/page.tsx');
    assert.equal(row?.hasUseClient, true);
    assert.equal(row?.justified, false);
  });

  it('no se deja fooled por la palabra onClick en un string de copy', () => {
    // Un grep por "onClick" habria dado este fichero por bueno.
    const rows = auditTemp({
      'components/Copy.tsx': `'use client';

export function Copy() {
  return <p>Pulsa onClick para continuar</p>;
}
`,
    });
    assert.equal(rows.find((r) => r.rel === 'components/Copy.tsx')?.justified, false);
  });

  it('no se deja fooled por un useState declarado en el propio fichero', () => {
    // El detector mira el AST: un `function useState()` local no es el hook.
    const rows = auditTemp({
      'components/Fake.tsx': `'use client';

function useState<T>(initial: T): [T, () => void] {
  return [initial, () => {}];
}

export function Fake() {
  const [v] = useState('hola');
  return <span>{v}</span>;
}
`,
    });
    assert.equal(rows.find((r) => r.rel === 'components/Fake.tsx')?.justified, false);
  });
});

describe('el guard no muerde de mas (controles positivos)', () => {
  const CONTROL = `'use client';

%BODY%
`;

  /** Analiza un unico fichero con el MISMO camino que el guard del repo. */
  const justify = (body: string, rel = 'components/C.tsx') => {
    const rows = auditUseClient([analyzeSource(rel, CONTROL.replace('%BODY%', body))]);
    return rows[0];
  };

  const cases: Array<[string, string]> = [
    ['hook de estado', `import { useState } from 'react';\nexport function C() { const [a] = useState(1); return <p>{a}</p>; }`],
    ['efecto', `import { useEffect } from 'react';\nexport function C() { useEffect(() => {}, []); return <p />; }`],
    ['ref', `import { useRef } from 'react';\nexport function C() { const r = useRef(null); return <p />; }`],
    ['handler JSX', `export function C() { return <button onClick={() => {}}>x</button>; }`],
    ['usePathname', `import { usePathname } from 'next/navigation';\nexport function C() { return <p>{usePathname()}</p>; }`],
    ['useFormStatus', `import { useFormStatus } from 'react-dom';\nexport function C() { return <p>{useFormStatus().pending}</p>; }`],
    ['global de navegador', `export function C() { return <p>{typeof window}</p>; }`],
    ['dynamic ssr:false', `import dynamic from 'next/dynamic';\nconst D = dynamic(() => import('./D'), { ssr: false });\nexport function C() { return <D />; }`],
    ['libreria cliente', `import * as Tooltip from '@radix-ui/react-tooltip';\nexport function C() { return <div />; }`],
    ['spread de props', `export function C(p: object) { return <div {...p} />; }`],
  ];

  for (const [name, body] of cases) {
    it(`da por buena una directiva con ${name}`, () => {
      const row = justify(body);
      assert.equal(row.hasUseClient, true);
      assert.equal(row.justified, true, `una directiva con ${name} debe justificarse; reasons: ${row.reasons.join(', ')}`);
    });
  }

  it('da por buena una directiva que importa otro modulo cliente', () => {
    // Sin la directiva, este import seria un modulo de servidor importando
    // uno de cliente a traves de un tercero: Next lo resuelve, pero la
    // intencion del autor es clara y la directiva es lo que evita el error
    // de boundary en el ancestro comun.
    const analyzed = [
      analyzeSource('components/Leaf.tsx', `'use client';\nimport * as T from '@radix-ui/react-tooltip';\nexport function Leaf() { return <div />; }`),
      analyzeSource('components/Mid.tsx', `'use client';\nimport { Leaf } from './Leaf';\nexport function Mid() { return <Leaf />; }`),
    ];
    const rows = auditUseClient(analyzed);
    const mid = rows.find((r) => r.rel === 'components/Mid.tsx');
    assert.equal(mid?.justified, true, 'importar un modulo cliente justifica la directiva');
  });
});

describe('la lista de excepciones no crece sin motivo', () => {
  const MIN_REASON_LENGTH = 80;

  for (const [label, exceptions, subdir] of [
    ['components/', COMPONENTS_EXCEPTIONS, 'components'],
    ['app/', APP_EXCEPTIONS, 'app'],
  ] as Array<[string, Record<string, string>, string]>) {
    it(`cada excepcion de ${label} tiene un motivo escrito de verdad`, () => {
      for (const [rel, reason] of Object.entries(exceptions)) {
        assert.ok(rel.startsWith(`${subdir}`), `la excepcion ${rel} no pertenece a ${subdir}`);
        assert.equal(typeof reason, 'string', `${rel}: el motivo debe ser un string`);
        assert.ok(
          reason.trim().length >= MIN_REASON_LENGTH,
          `${rel}: motivo demasiado corto (${reason.trim().length} < ${MIN_REASON_LENGTH} caracteres). Una excepcion sin explicar es una barrera silenciosa.`,
        );
        assert.doesNotMatch(
          reason.trim(),
          /^(todo|tbd|porque si|fixme|pendiente|revisar|\?+)$/i,
          `${rel}: motivo de relleno, no vale.`,
        );
      }
    });

    it(`cada excepcion de ${label} sigue siendo necesaria`, () => {
      // Una excepcion que ya no aplica (el fichero quito la directiva, o
      //yncio un hook de verdad) es basura que hay que borrar, no deuda que
      // se arrastra: es la via por la que estas listas crecen solas.
      for (const [rel] of Object.entries(exceptions)) {
        assert.ok(existsSync(join(root, rel)), `${rel}: la excepcion apunta a un fichero que no existe. Bórrala.`);
        const row = byRel.get(rel);
        assert.ok(row, `${rel}: la excepcion apunta a un fichero que el auditor no encuentra. Bórrala.`);
        assert.equal(row.hasUseClient, true, `${rel}: ya no tiene 'use client', la excepcion es obsoleta. Bórrala.`);
        assert.equal(
          row.justified,
          false,
          `${rel}: ya tiene una señal de cliente que justifica la directiva. Bórrala de las excepciones.`,
        );
      }
    });
  }
});

describe('el escaner y el guard cuentan lo mismo', () => {
  it('LibraryChat justifica su directiva por estado y envío interactivo', () => {
    const row = byRel.get('app/(root)/inversores/_components/LibraryChat.tsx');
    assert.ok(row);
    assert.equal(row.hasUseClient, true);
    assert.equal(row.justified, true, 'preguntas, respuesta y estado busy/error requieren hooks y eventos');
  });

  it('scan-use-client.mjs no reporta ninguna clase (B)', () => {
    // El escaner es la herramienta de lectura humana y el guard el que
    // bloquea. Si se desincronizasen, el guard pasaria en verde mientras el
    // inventario que se lee en la revision-prompts dice otra cosa.
    const rows = auditRepo(root, ['components', 'app', 'hooks', 'lib']);
    const dead = rows.filter((r) => r.hasUseClient && !r.justified && !(r.rel in COMPONENTS_EXCEPTIONS) && !(r.rel in APP_EXCEPTIONS));
    assert.deepEqual(
      dead.map((r) => r.rel).sort(),
      [],
      'el detector compartido encuentra directivas muertas que las excepciones no cubren',
    );
  });

  it('el numero de directivas client del repo no crece sin explicacion', () => {
    // 100 = SyncPortfoliosButton: useState del estado de sincronizacion y onClick que llama a la server action (inversores/carteras en cuenta nueva).
    // 99 = IngestLettersButton: useState del estado de descarga y onClick que llama a la server action (inversores/cartas con biblioteca vacia).
    // 98 = NewsSecondOrder (useState y onToggle del <details> que carga el segundo orden bajo demanda) + TaxDeclarantForm (useState de los campos fiscales y envío del formulario en /settings): ambas justificadas por hooks y eventos, no heredadas.
    // 96 = ThesisAudioPlayer: useState/useRef/useSyncExternalStore y handlers de play/pausa/detener sobre window.speechSynthesis (la lectura en voz alta solo existe en el navegador).
    // 95 = PublicMobileNav: useState del drawer, listeners de teclado (Escape/Tab), matchMedia para cerrar al cruzar md y bloqueo de scroll del body en el header publico.
    // 94 = AccessRequestForm: useState (envio, error y confirmacion) y onSubmit del formulario de solicitud de acceso con el registro cerrado.
    // 93 = HistoricalStressView: useState (paginacion de la tabla de ventanas) en la pagina /portfolio/stress.
    // 92 = ShareCapitalPanel: useState (pestanas saldos/flujos y paginacion) y recharts, que solo funciona en cliente.
    // 91 = ChangesSinceVisit: localStorage/sessionStorage + fetch en cliente (la ultima visita solo existe en el navegador).
    // 90 = InstallApp: beforeinstallprompt, useState/useEffect y click para instalar la PWA (seccion Instalar GerarAI en /security).
    // 89 = ThesisExportMenu: DropdownMenu Radix interactivo (trigger, items, teclado) que agrupa las 4 exportaciones de la tesis.
    // 88 = CompanyHeaderQuote: useEffect/useState, refresco 60s y visibilitychange para cotización extendida.
    // 87 = NextStepLink: onClick para llevar la pantalla al inicio al cambiar de vista de la ficha (en movil el enlace esta al final de una pagina larga); 86 = TmePreviewForm: useState para el campo TME, validacion y envio del formulario; 85 = HubNav: usePathname para la sección activa de la biblioteca. 84 = LibraryChat: useState para pregunta/autor/respuesta/busy/error y eventos onSubmit/onChange;
    // requiere interactividad real, no es excepción heredada. 83 = NewsHeadline adds visible-only async translation state/IntersectionObserver; 82 = 77 justificadas (SectionNav: usePathname para contexto de rutas) y antes 81 = 76 justificadas (CompanyTechnicalChart: hooks/canvas/rangos; CompanyTechnicalWorkspace: dynamic ssr:false) + 5 heredadas. Antes: 79 = 74 justificadas (A, incluye KnowledgeGraphCanvas: eventos de puntero, pan/zoom y BottomNav: usePathname; YouTubeEmbed: useState para cargar tras clic) + 5 heredadas del padre (C). Si sube, alguien
    // ha anadido un modulo cliente: que lo justifique en la revision.
    const total = audit.filter((r) => r.hasUseClient).length;
    const justified = audit.filter((r) => r.hasUseClient && r.justified).length;
    const inherited = audit.filter((r) => r.hasUseClient && !r.justified).length;
    assert.equal(inherited, 5, 'cambian las excepciones: revisa COMPONENTS_EXCEPTIONS y su motivo');
    assert.equal(
      total,
      100,
      `han aparecido directivas 'use client' sin revisar (total ${total}, justificadas ${justified}, heredadas ${inherited})`,
    );
  });
});
