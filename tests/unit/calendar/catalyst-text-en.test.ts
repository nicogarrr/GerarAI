import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import type { CatalystType } from '@/lib/actions/catalysts.actions';
import { catalystActionTitle, catalystDetailText } from '@/lib/calendar/catalyst-text';

// Salida real de catalyst_calendar_service.build_catalysts y
// filing_deadline_event (generada con esas funciones): título y detalle.
const EVENTS: { type: CatalystType; title: string; detail: string | null }[] = [
  {
    "type": "dividend_ex",
    "title": "Fecha ex-dividendo",
    "detail": "0,1000 EUR por acción"
  },
  {
    "type": "earnings",
    "title": "Resultados trimestrales",
    "detail": "tras el cierre, BPA estimado 1,23"
  },
  {
    "type": "dividend_payment",
    "title": "Pago de dividendo",
    "detail": "0,1000 EUR por acción"
  },
  {
    "type": "earnings",
    "title": "Resultados trimestrales",
    "detail": "hora por confirmar"
  },
  {
    "type": "earnings",
    "title": "Resultados trimestrales",
    "detail": "antes de la apertura, BPA estimado -0,50"
  },
  {
    "type": "dividend_ex",
    "title": "Fecha ex-dividendo",
    "detail": "0,2600 por acción · pago el 13/11/2026"
  },
  {
    "type": "dividend_ex",
    "title": "Fecha ex-dividendo",
    "detail": "pago el 13/11/2026"
  },
  {
    "type": "corporate_action",
    "title": "Split",
    "detail": "ratio 4"
  },
  {
    "type": "corporate_action",
    "title": "Contrasplit",
    "detail": "ratio 0,1"
  },
  {
    "type": "corporate_action",
    "title": "Fusion",
    "detail": null
  },
  {
    "type": "corporate_action",
    "title": "Cambio de ticker",
    "detail": null
  },
  {
    "type": "corporate_action",
    "title": "Escision",
    "detail": null
  },
  {
    "type": "corporate_action",
    "title": "Acción corporativa",
    "detail": null
  },
  {
    "type": "filing_deadline",
    "title": "Plazo para presentar el 10-K",
    "detail": "60 días tras el cierre de periodo estimado (26 sept 2026) sobre el último informe periódico (cierre 27 jun 2026); emisor de 52/53 semanas: fecha aproximada (hasta ~1 semana); categoría EDGAR: emisor acelerado grande"
  },
  {
    "type": "filing_deadline",
    "title": "Plazo para presentar el 10-Q",
    "detail": "45 días tras el cierre de periodo estimado (30 jun 2026) sobre el último informe periódico (cierre 31 mar 2026); categoría de filer no disponible: se usa el plazo máximo de la regla"
  },
  {
    "type": "filing_deadline",
    "title": "Plazo para presentar el 10-Q",
    "detail": "45 días tras el cierre de periodo estimado (30 jun 2026) sobre el último informe periódico (cierre 31 mar 2026); categoría de filer no disponible: se usa el plazo máximo de la regla"
  }
];
const SPANISH = /por acción|pago el|BPA|apertura|cierre|hora por|días|emisor|categoría|plazo|Contrasplit|Fusion|Escision|Cambio de ticker|Acción corporativa|\d,\d/;

describe('calendario de catalizadores en inglés', () => {
  it('cada detalle y cada acción corporativa reales salen en inglés', () => {
    for (const event of EVENTS) {
      const detail = catalystDetailText(event, 'en');
      if (event.detail) expect(detail, event.detail).not.toMatch(SPANISH);
      if (event.type === 'corporate_action') expect(catalystActionTitle(event.title, 'en'), event.title).not.toMatch(SPANISH);
    }
  });

  it('frases concretas', () => {
    const detail = (type: string, text: string) => catalystDetailText({ type: type as CatalystType, detail: text }, 'en');
    expect(detail('earnings', 'tras el cierre, BPA estimado 1,23')).toBe('after the close, estimated EPS 1.23');
    expect(detail('dividend_ex', '0,2600 por acción · pago el 13/11/2026')).toBe('0.2600 per share · paid on Nov 13, 2026');
    expect(detail('dividend_payment', '0,1000 EUR por acción')).toBe('0.1000 EUR per share');
    expect(detail('corporate_action', 'ratio 0,1')).toBe('ratio 0.1');
    expect(detail('filing_deadline', EVENTS.find((e) => e.type === 'filing_deadline')!.detail!)).toBe(
      '60 days after the estimated period end (Sep 26, 2026) based on the latest periodic report (period end Jun 27, 2026); 52/53-week issuer: approximate date (up to ~1 week); EDGAR category: large accelerated filer',
    );
    expect(catalystActionTitle('Contrasplit', 'en')).toBe('Reverse split');
  });

  it('en castellano, o con un trozo desconocido, el texto pasa entero', () => {
    for (const event of EVENTS) expect(catalystDetailText(event, 'es')).toBe(event.detail);
    expect(catalystDetailText({ type: 'earnings', detail: 'tras el cierre, algo nuevo' }, 'en')).toBe('tras el cierre, algo nuevo');
    expect(catalystActionTitle('Contrasplit', 'es')).toBe('Contrasplit');
  });

  it('el backend sigue escribiendo estas frases y la pantalla las pasa por el idioma', () => {
    const py = readFileSync('data-engine/app/services/catalyst_calendar_service.py', 'utf8');
    for (const text of ['"hora por confirmar"', 'f"BPA estimado {', ' por acción"', 'f"pago el {pay.day}/{pay.month}/{pay.year}"', '"reverse_split": "Contrasplit"', 'f"ratio {', 'categoría de filer no disponible: se usa el plazo máximo de la regla', 'f"; categoría EDGAR: {']) {
      expect(py).toContain(text);
    }
    const view = readFileSync('components/calendar/CalendarEvents.tsx', 'utf8');
    expect(view).toContain('catalystActionTitle(event.title, f.locale)');
    expect(view).toContain('catalystDetailText(event, f.locale)');
  });
});
