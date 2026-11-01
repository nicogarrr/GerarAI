import { describe, expect, it } from 'vitest';

import { backendMessage } from '@/lib/research/backend-error-es';

describe('thesis criteria, export and official-source engine messages in English', () => {
  it('translates them with English selected', () => {
    expect(backendMessage("Criterio 2: métrica no soportada «roe»", 'en')).toBe("Criterion 2: unsupported metric «roe».");
    expect(backendMessage("Máximo 20 criterios de invalidación por tesis.", 'en')).toBe("At most 20 invalidation criteria per thesis.");
    expect(backendMessage("Value error, Criterio 1: el umbral debe ser un número finito.", 'en')).toBe("Criterion 1: the threshold must be a finite number.");
    expect(backendMessage("No hay ninguna versión de tesis para AAPL", 'en')).toBe("There is no thesis version for AAPL.");
    expect(backendMessage("Ticker no encontrado", 'en')).toBe("Ticker not found.");
    expect(backendMessage("Sin CIK para SAN.MC: este emisor no reporta a la SEC; usa la fuente de su mercado local (ESEF para emisores de la UE)", 'en')).toBe("No CIK for SAN.MC: this issuer does not report to the SEC; use its local market source (ESEF for EU issuers).");
  });

  it('leaves them in Spanish with Spanish selected', () => {
    expect(backendMessage('Criterio 2: métrica no soportada «roe».', 'es')).toBe('Criterio 2: métrica no soportada «roe».');
  });
});
