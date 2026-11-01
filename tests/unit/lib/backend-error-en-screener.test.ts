import { describe, expect, it } from 'vitest';

import { backendMessage } from '@/lib/research/backend-error-es';

describe('screener, library document and calendar engine messages in English', () => {
  it('translates them with English selected', () => {
    expect(backendMessage("Ya existe un filtro con ese nombre", 'en')).toBe("A filter with that name already exists.");
    expect(backendMessage("La fórmula supera los 1000 caracteres", 'en')).toBe("The formula exceeds 1000 characters.");
    expect(backendMessage("Nombre de métrica no válido: roic_x", 'en')).toBe("Invalid metric name: roic_x");
    expect(backendMessage("max requiere al menos 2 argumentos", 'en')).toBe("max takes at least 2 arguments.");
    expect(backendMessage("Elemento de fórmula Lambda no permitido", 'en')).toBe("Formula element Lambda not allowed.");
    expect(backendMessage("El ticker no es válido (ej.: AAPL, BRK-B, SAN.MC)", 'en')).toBe("The ticker is not valid (e.g. AAPL, BRK-B, SAN.MC).");
    expect(backendMessage("El documento descomprimido supera el limite real de ingesta", 'en')).toBe("The uncompressed document exceeds the ingestion limit.");
    expect(backendMessage("El documento tiene datos ZIP truncados", 'en')).toBe("The document has a damaged ZIP structure.");
    expect(backendMessage("Las dimensiones del XLSX superan el limite de ingesta", 'en')).toBe("The XLSX's dimensions exceed the ingestion limit.");
    expect(backendMessage("\"desde\" no puede ser posterior a \"hasta\"", 'en')).toBe("\"From\" cannot be after \"to\".");
    expect(backendMessage("fecha fuera de rango", 'en')).toBe("Date out of range.");
  });

  it('leaves them in Spanish with Spanish selected', () => {
    expect(backendMessage('Ya existe un filtro con ese nombre', 'es')).toBe('Ya existe un filtro con ese nombre');
  });
});
