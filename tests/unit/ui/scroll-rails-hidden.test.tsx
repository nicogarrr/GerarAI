import React from 'react';
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ChangesFeed } from '@/components/research/ChangesFeed';
import { CalendarTabs } from '@/components/calendar/CalendarTabs';
import HelpTabs from '@/components/help/HelpTabs';
import { LocaleProvider } from '@/lib/i18n/client';

// Mismo patrón que la ficha (CompanyNavigation): los raíles horizontales por
// toque no muestran la pista de scroll pero siguen deslizando.
vi.mock('next/navigation', () => ({ usePathname: () => '/calendar' }));
const support = vi.hoisted(() => ({ email: 'help@example.invalid' }));
vi.mock('@/lib/config/brand', () => ({ get SUPPORT_EMAIL() { return support.email; } }));

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

const mk = (id: number) => ({
  id, company_id: 1, from_version_id: null, to_version_id: null, change_type: 'news_material_update', impact_direction: 'positive',
  materiality_score: 60, summary: `Suceso ${id}`, affected_claim_ids: [], affected_metrics: [], requires_review: false,
  created_at: `2026-10-${String(id % 28 + 1).padStart(2, '0')}T10:00:00Z`, updated_at: '',
});

describe('raíles horizontales táctiles: scroll oculto, deslizar intacto', () => {
  it('ChangesFeed: raíl de filtros oculta la barra', () => {
    render(<ChangesFeed alerts={[]} changes={[mk(1)]} reviews={[]} ticker="ASTS" />);
    const rail = screen.getByRole('button', { name: /^Todos/ }).parentElement!;
    expect(rail.className).toContain('overflow-x-auto');
    expect(rail.className).toContain('scrollbar-hide');
  });

  it('CalendarTabs: el nav de pestañas oculta la barra', () => {
    render(<CalendarTabs />);
    const rail = screen.getByRole('navigation');
    expect(rail.className).toContain('overflow-x-auto');
    expect(rail.className).toContain('scrollbar-hide');
  });

  it('HelpTabs: la tablist oculta la barra', () => {
    render(<LocaleProvider locale="es"><HelpTabs /></LocaleProvider>);
    const rail = screen.getByRole('tablist', { name: 'Secciones de la ayuda' });
    expect(rail.className).toContain('overflow-x-auto');
    expect(rail.className).toContain('scrollbar-hide');
  });

  it('PoliticiansListSection y EarningsDayStrip declaran scrollbar-hide en sus raíles', () => {
    // Raíles con fixtures pesados: la invariante es de clase en la fuente.
    for (const [file, needle] of [
      ['components/insider/PoliticiansListSection.tsx', 'overflow-x-auto'],
      ['components/calendar/EarningsDayStrip.tsx', 'overflow-x-auto'],
    ] as const) {
      const src = readFileSync(file, 'utf8');
      const railLines = src.split('\n').filter((line) => line.includes(needle) && line.includes('className'));
      expect(railLines.length).toBeGreaterThan(0);
      for (const line of railLines) expect(line).toContain('scrollbar-hide');
    }
  });
});
