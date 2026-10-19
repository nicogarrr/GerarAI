// Regla espejo de needs_translation (data-engine/app/services/public_headline_translation.py):
// el botón «Traducir» aparece exactamente cuando el backend intentará traducir.
// Tester 4 nº6 (19-oct-2026): filas Yahoo con y sin botón por huecos de la
// heurística inglesa. Decisión del auditor: sin marcas claras NO es traducible
// («Inditex bate previsiones» no gasta presupuesto), salvo señal latina-inglesa
// explícita: titular en Title Case de >=3 palabras, convención de prensa anglosajona.
// Paridad con Python (objeción del auditor, 19-oct): el \b de JS es ASCII y rompe
// con acentos («compañías» casaba «as» como palabra inglesa); se usan lookarounds
// Unicode con flag u en lugar de \b, equivalentes al \b Unicode de Python.
const WORD_L = String.raw`(?<![\p{L}\p{N}_])`;
const WORD_R = String.raw`(?![\p{L}\p{N}_])`;
const NON_LATIN = /[\u0370-\u03ff\u0400-\u052f\u0600-\u06ff\u0900-\u097f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/;
const ENGLISH_MARK = new RegExp(WORD_L + '(the|with|says|shares|stocks|earnings|reports|raises|falls|after|amid|outlook|growth|investors|market|billion|million|revenue|warns|cuts|for|and|as|to|in)' + WORD_R, 'iu');
const SPANISH_MARK = new RegExp(WORD_L + '(el|la|los|las|una?|de|del|que|en|para|por|con|sus|más|años?|empresa|acciones|según|tras|sobre|está|están|han|será|anuncia|sube|baja|informa)' + WORD_R + '|[áéíóúñ]|[¿¡]', 'iu');
const TITLE_CASE_WORD = new RegExp(WORD_L + '[A-ZÁÉÍÓÚÑ][a-záéíóúñü]{2,}' + WORD_R, 'gu');

export function isTranslatable(text: string): boolean {
    if (NON_LATIN.test(text)) return true;
    if (ENGLISH_MARK.test(text)) return true;
    if (SPANISH_MARK.test(text)) return false;
    TITLE_CASE_WORD.lastIndex = 0;
    return (text.match(TITLE_CASE_WORD) ?? []).length >= 3;
}
