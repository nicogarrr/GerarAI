import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

// Convención táctil de los <summary> interactivos (WCAG 2.5.5): reservan
// 44px reales en móvil (min-h-11 py-2) y vuelven a 40px en escritorio
// (sm:min-h-10). SIN display:flex/inline-flex: eso elimina el marcador
// nativo de despliegue del <summary>.
//
// El guard selecciona TODOS los <summary> elegibles de cada fichero — con o
// sin className — y excluye explícitamente los que no entran. Seleccionar
// solo los que ya llevan min-h-1x dejaría pasar una regresión: un summary
// revertido deja de coincidir con el filtro y desaparece de la muestra
// (bug de cobertura detectado en la auditoría de #5641).
const FILES = [
  'components/alerts/AlertsManager.tsx',
  'components/PersonalizedOverview.tsx',
  'components/portfolio/PortfolioDataNotice.tsx',
  'app/(root)/search/page.tsx',
  'components/ErrorBoundary.tsx',
  'components/brain/BrainGuideAnswer.tsx',
  'components/paper-trading/PositionsTable.tsx',
  'components/portfolio/ImportImageButton.tsx',
  'components/portfolio/PortfolioDividends.tsx',
  'components/proPicks/PaperTradingView.tsx',
  'components/research/ExternalNewsHeadline.tsx',
  'components/research/MoatPanel.tsx',
  'components/research/ScenarioAssumptions.tsx',
  'components/research/sections/ManagementAlignmentSection.tsx',
  'components/research/SotpBreakdownSection.tsx',
  'components/research/ThesisHumanInputForm.tsx',
  'components/research/ThesisInvalidationRulesForm.tsx',
];

// <summary> excluidos de la convención, fichero + marca textual del propio tag:
//   - search: el toggle de filtros avanzados lleva list-none + icono propio;
//     su flex es intencional (no es un details de texto).
const EXCLUDED = [
  { file: 'app/(root)/search/page.tsx', marker: 'list-none' },
];

const SUMMARY_TAG = /<summary\b[^>]*>/g;

for (const file of FILES) {
  test(`guard móvil: summary táctil 44px con marcador nativo (${file})`, () => {
    const source = readFileSync(file, 'utf8');
    const tags = [...source.matchAll(SUMMARY_TAG)].map((m) => m[0]);
    const eligible = tags.filter((tag) => !EXCLUDED.some((x) => x.file === file && tag.includes(x.marker)));
    assert.ok(eligible.length > 0, `no se encontraron <summary> elegibles en ${file}`);
    for (const tag of eligible) {
      const classes = /className="([^"]*)"/.exec(tag)?.[1] ?? '';
      assert.ok(
        /\bmin-h-11\b/.test(classes) && /\bpy-2\b/.test(classes) && /\bsm:min-h-10\b/.test(classes),
        `<summary> sin la convención táctil (min-h-11 py-2 sm:min-h-10) en ${file}: ${tag.slice(0, 120)}`,
      );
      assert.ok(
        !/(^|\s)(inline-)?flex(\s|$)/.test(classes),
        `<summary> con display flex pierde el marcador nativo en ${file}: ${tag.slice(0, 120)}`,
      );
    }
  });
}
