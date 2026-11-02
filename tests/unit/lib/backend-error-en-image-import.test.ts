import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { imagePreviewMessage } from '@/lib/portfolio/image-import';
import { backendMessage } from '@/lib/research/backend-error-es';
import { createTranslator } from '@/lib/i18n/translate';

// Frases reales de portfolio_image_ocr.py (leídas del .py: si cambian, el test lo nota).
const OCR = readFileSync('data-engine/app/services/portfolio_image_ocr.py', 'utf8');
const pick = (re: RegExp): string => {
    const m = OCR.match(re);
    if (!m) throw new Error(`no encontrado: ${re}`);
    return m[1];
};
const BUSY = pick(/RuntimeError\("(Hay otra captura en lectura[^"]+)"\)/);
const UNREADABLE = pick(/ValueError\("(No se puede leer esta imagen[^"]+)"\)/);
const NO_ROWS = pick(/else "(No se reconocieron filas[^"]+)"/);
const ROWS = pick(/"message": "(Selecciona explícitamente[^"]+)"/);

describe('importar cartera desde imagen: frases del backend en inglés', () => {
    it('los errores de lectura de la captura salen en inglés', () => {
        expect(backendMessage(BUSY, 'en')).toBe('Another screenshot is being read. Retry in a few seconds.');
        expect(backendMessage(UNREADABLE, 'en')).toBe('This image cannot be read; try another screenshot.');
        expect(backendMessage(BUSY, 'es')).toBe(BUSY);
    });

    it('el aviso de «no se reconocieron filas» sale en inglés; en castellano, tal cual', () => {
        expect(imagePreviewMessage(NO_ROWS, createTranslator('en'))).toBe(
            'No rows with a quantity header were recognised. Crop the table including the header, or use a file or manual entry.',
        );
        expect(imagePreviewMessage(ROWS, createTranslator('en'))).toBe(
            'Pick each instrument explicitly and review the rows. Prices in the screenshot are not imported.',
        );
        expect(imagePreviewMessage(NO_ROWS, createTranslator('es'))).toBe(NO_ROWS);
        expect(imagePreviewMessage('Otra cosa', createTranslator('en'))).toBe('Otra cosa');
    });
});
