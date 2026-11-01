import { describe, expect, it } from 'vitest';

import { backendMessage } from '@/lib/research/backend-error-es';

describe('import, IBKR identity, journal and AI-provider engine messages in English', () => {
  it('translates them with English selected, keeping row numbers and values', () => {
    expect(backendMessage("Fila 3: precio fuera de rango (1e30); revisa el archivo y vuelve a generar la vista previa", 'en')).toBe("Row 3: precio out of range (1e30); check the file and generate the preview again.");
    expect(backendMessage("Fila 4: la fecha es anterior a 1900 (1800-01-01): revisa el año", 'en')).toBe("Row 4: the date is before 1900 (1800-01-01): check the year.");
    expect(backendMessage("Fila 2: ticker no válido ('A..B'); revisa el archivo y vuelve a generar la vista previa", 'en')).toBe("Row 2: invalid ticker ('A..B'); check the file and generate the preview again.");
    expect(backendMessage("El archivo supera el máximo de 5000 filas; divídelo en varios lotes", 'en')).toBe("The file exceeds the maximum of 5000 rows; split it into several batches.");
    expect(backendMessage("Importe no interpretable: '1.2.3'. Usa notacion en-US (1,234.56) o es-ES (1.234,56).", 'en')).toBe("Amount could not be read: '1.2.3'. Use en-US (1,234.56) or es-ES (1.234,56) notation.");
    expect(backendMessage("La operación no es de AAPL.", 'en')).toBe("The trade is not for AAPL.");
    expect(backendMessage("Has cambiado de proveedor o de URL: introduce la API key para el nuevo destino (la clave guardada no se envia a otro sitio).", 'en')).toBe("You changed the provider or URL: enter the API key for the new destination (the saved key is never sent elsewhere).");
    expect(backendMessage("Value error, La base_url debe usar HTTPS.", 'en')).toBe("The base_url must use HTTPS.");
  });

  it('leaves them in Spanish with Spanish selected', () => {
    expect(backendMessage("Fila 4: la fecha es anterior a 1900 (1800-01-01): revisa el año", 'es')).toBe("Fila 4: la fecha es anterior a 1900 (1800-01-01): revisa el año");
  });
});
