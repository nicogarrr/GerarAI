import { readFileSync } from 'node:fs';
import path from 'node:path';
import { Suspense } from 'react';
import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// El navegador resuelve `#i18n-en-compact` con la condición `browser`: sin
// inglés en el chunk común y con descarga aparte. Aquí se simula ese módulo.
const { loadSpy } = vi.hoisted(() => ({
  loadSpy: vi.fn(async () => (await import('@/lib/i18n/messages/en.compact.json')).default),
}));
vi.mock('#i18n-en-compact', () => ({ bundledCompactEnglish: null, loadCompactEnglish: loadSpy }));

const root = path.resolve(__dirname, '../../..');

describe('inglés fuera del chunk común del navegador', () => {
  it('package.json manda al navegador un módulo sin el JSON inglés estático', () => {
    const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
    const entry = pkg.imports?.['#i18n-en-compact'];
    expect(entry?.browser).toBe('./lib/i18n/messages/en-compact.browser.ts');
    expect(entry?.default).toBe('./lib/i18n/messages/en-compact.ts');
    const browserSource = readFileSync(path.join(root, entry.browser), 'utf8');
    expect(browserSource).not.toMatch(/^import\s+\w+\s+from\s+['"]\.\/en\.compact\.json['"]/m);
    expect(browserSource).toMatch(/import\(['"]\.\/en\.compact\.json['"]\)/);
    const registry = readFileSync(path.join(root, 'lib/i18n/messages/index.ts'), 'utf8');
    expect(registry).not.toMatch(/from\s+['"]\.\/en\.compact\.json['"]/);
  });

  it('en castellano no descarga el inglés; en inglés lo carga antes de pintar', async () => {
    const { LocaleProvider, useT } = await import('@/lib/i18n/client');
    const { hasEnglishMessages } = await import('@/lib/i18n/messages');
    function Probe() {
      const t = useT();
      return <span>{t('common.actions.save')}</span>;
    }
    expect(hasEnglishMessages()).toBe(false);
    const es = render(<LocaleProvider locale="es"><Probe /></LocaleProvider>);
    expect(screen.getByText('Guardar')).toBeInTheDocument();
    expect(loadSpy).not.toHaveBeenCalled();
    es.unmount();

    await act(async () => {
      render(<Suspense fallback={<span>cargando</span>}><LocaleProvider locale="en"><Probe /></LocaleProvider></Suspense>);
    });
    expect(await screen.findByText('Save')).toBeInTheDocument();
    expect(screen.queryByText('Guardar')).not.toBeInTheDocument();
    expect(loadSpy).toHaveBeenCalledTimes(1);
    expect(hasEnglishMessages()).toBe(true);
  });
});
