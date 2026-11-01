import { describe, expect, it } from 'vitest';
import { createTranslator } from '@/lib/i18n/translate';
import { BOTTLENECK_TO_THEMES, THEME_TO_BOTTLENECK, basketName, bottleneckThemeName } from '@/lib/market/theme-bottleneck-map';
import { formatRecordValue } from '@/components/data/RecordViews';

const es = createTranslator('es');
const en = createTranslator('en');

describe('nombres de cestas y temas de escasez según el idioma', () => {
  it('en inglés, las cestas y los temas de escasez conocidos salen traducidos', () => {
    expect(basketName('materiales', 'Materiales críticos', en)).toBe('Critical materials');
    expect(basketName('centros-de-datos', 'Centros de datos', en)).toBe('Data centers');
    expect(bottleneckThemeName('Industria aeroespacial', en)).toBe('Aerospace industry');
    expect(bottleneckThemeName('Energía', en)).toBe('Energy');
  });

  it('en español se mantienen los nombres del motor', () => {
    for (const themes of Object.values(BOTTLENECK_TO_THEMES)) {
      for (const theme of themes) expect(basketName(theme.id, 'x', es)).toBe(theme.name);
    }
    for (const theme of new Set(Object.values(THEME_TO_BOTTLENECK))) expect(bottleneckThemeName(theme, es)).toBe(theme);
    expect(bottleneckThemeName('Transporte', es)).toBe('Transporte');
  });

  it('una cesta o tema desconocido conserva el nombre que manda el motor', () => {
    expect(basketName('nueva-cesta', 'Cesta nueva', en)).toBe('Cesta nueva');
    expect(basketName('constructor', 'Otra', en)).toBe('Otra');
    expect(bottleneckThemeName('Agua', en)).toBe('Agua');
  });
});

describe('resumen de listas largas en celdas', () => {
  it('cuenta lo que no cabe en el idioma elegido', () => {
    const value = Array.from({ length: 9 }, (_, i) => i + 1);
    expect(formatRecordValue(value, en)).toMatch(/· \+\d+ more$/);
    expect(formatRecordValue(value, es)).toMatch(/· \+\d+ más$/);
  });
});
