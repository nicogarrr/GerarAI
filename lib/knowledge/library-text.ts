import type { TranslationKey } from '@/lib/i18n/t';
import type { TranslateFn } from '@/lib/i18n/translate';
import { translateMessage } from '@/lib/i18n/translate';

/**
 * Avisos de la biblioteca (knowledge_chat.py `message` y knowledge_analysis.py
 * `aviso` y `probabilidades`): el backend los manda solo en castellano. El catálogo en castellano
 * guarda la misma frase; si coincide, se muestra la clave en el idioma activo.
 * Un texto distinto pasa tal cual.
 */
const LIBRARY_TEXT_KEYS: readonly TranslationKey[] = [
  'brain.library.messages.analysisUnavailable',
  'brain.library.messages.synthesisUnavailable',
  'brain.library.messages.notAnswered',
  'brain.library.messages.modelNotApproved',
  'brain.library.messages.citationsRejected',
  'brain.library.messages.providerDown',
  'brain.library.messages.noFragments',
  'brain.library.disclaimer',
  'brain.library.probabilityNote',
];

export function libraryText(text: string, t: TranslateFn): string {
  const key = LIBRARY_TEXT_KEYS.find((k) => translateMessage('es', k) === text);
  return key ? t(key) : text;
}
