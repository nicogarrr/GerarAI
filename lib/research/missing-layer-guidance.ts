/**
 * Orientación por capa de research faltante (F305).
 *
 * El aviso «Capas de research que faltan» mandaba siempre a importar
 * documentos, incluso cuando lo que falta es la tesis o el modelo: importar
 * fuentes no genera ninguna de las dos. Cada capa tiene su destino y su
 * verbo; una capa desconocida NO inventa ruta (sin enlace). Los textos salen
 * en el idioma elegido (por defecto, español).
 */
// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

const LAYER_KEYS: Record<string, TranslationKey> = {
    documents: 'research.missingLayer.documents',
    financial_facts: 'research.missingLayer.financialFacts',
    thesis: 'research.missingLayer.thesis',
    long_term_model: 'research.missingLayer.longTermModel',
};

export function missingLayerLabel(layer: string, ti: TiFn = esT): string {
    const key = LAYER_KEYS[layer];
    if (key) return ti(key);
    // Capa no catalogada: se humaniza, nunca se oculta.
    const words = layer.replaceAll('_', ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

export type MissingLayerAction = { href: string; label: string };

export function missingLayerAction(ticker: string, layer: string, ti: TiFn = esT): MissingLayerAction | null {
    const base = `/research/${encodeURIComponent(ticker)}`;
    switch (layer) {
        case 'documents':
            return { href: `${base}?view=documents`, label: ti('research.missingLayer.actionDocuments') };
        case 'financial_facts':
            // La vista financieros tiene los botones «Refrescar SEC/FMP/ESEF».
            return { href: `${base}?view=financieros`, label: ti('research.missingLayer.actionFinancialFacts') };
        case 'thesis':
            return { href: `${base}?view=tesis`, label: ti('research.missingLayer.actionThesis') };
        case 'long_term_model':
            return { href: `${base}?view=modelo`, label: ti('research.missingLayer.actionLongTermModel') };
        default:
            return null;
    }
}
