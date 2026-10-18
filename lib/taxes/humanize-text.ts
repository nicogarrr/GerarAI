/** Claves internas del motor fiscal que nunca deben verse tal cual en pantalla. */
const REPLACEMENTS: Array<[RegExp, string]> = [
    [/tax_declarant\.custody_country/g, 'el país de custodia de tus datos de declarante'],
    [/tax_declarant\.custody_entities/g, 'las entidades de custodia de tus datos de declarante'],
    [/tax_declarant\.custody/g, 'la custodia por partida de tus datos de declarante'],
    [/'?\bcustody_entities\b'?/g, 'las entidades de custodia'],
    [/'?\bcustody_country\b'?/g, 'el país de custodia'],
    [/'?\bnumero_declaracion\b'?/g, 'el número de declaración'],
    [/'?\bapellidos_nombre\b'?/g, 'apellidos y nombre'],
    [/'?\bnif\b'?/g, 'el NIF'],
    // Frases completas primero: sustituir solo la clave dejaba «en la tus datos
    // fiscales bajo la los datos del declarante».
    [/(?:en\s+)?la\s+metadata\s+del\s+tenant\s+bajo\s+la\s+clave\s+'?tax_declarant'?/g, 'en tus datos fiscales, en los datos del declarante'],
    [/(?:en\s+)?la\s+metadata\s+del\s+tenant/g, 'en tus datos fiscales'],
    [/bajo\s+la\s+clave\s+'?tax_declarant'?/g, 'en los datos del declarante'],
    [/clave\s+'?tax_declarant'?/g, 'los datos del declarante'],
    [/'?\btax_declarant\b'?/g, 'los datos del declarante'],
    [/'?\bcustody\b'?/g, 'la custodia por partida'],
    [/\bmetadata del tenant\b/g, 'tus datos fiscales'],
    [/\bdel tenant\b/g, 'de tu cuenta'],
    [/\bcash[-:]([A-Z]{3})\b/g, 'caja $1'],
    // Jerga del motor: «snapshot» se dice «captura» en pantalla. Las frases
    // con concordancia van primero; lo genérico al final.
    [/Partidas con snapshot demasiado antiguo/g, 'Partidas con captura demasiado antigua'],
    [/con SU snapshot/g, 'con SU captura'],
    [/uno reciente no certifica a otro viejo/g, 'una reciente no certifica a otra vieja'],
    [/snapshot antiguo/g, 'captura antigua'],
    [/a fecha del snapshot/g, 'a fecha de la captura'],
    [/\bsnapshots\b/g, 'capturas'],
    [/\bSnapshots\b/g, 'Capturas'],
    [/\bsnapshot\b/g, 'captura'],
    [/\bSnapshot\b/g, 'Captura'],
    [/\bSIN_DATOS\b/g, 'N/D'],
];

export function humanizeTaxText(text: string): string {
    return REPLACEMENTS.reduce((acc, [pattern, value]) => acc.replace(pattern, value), text);
}
