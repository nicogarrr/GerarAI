/** Claves internas del motor fiscal que nunca deben verse tal cual en pantalla. */
const REPLACEMENTS: Array<[RegExp, string]> = [
    [/tax_declarant\.custody_country/g, 'el país de custodia de tus datos de declarante'],
    [/tax_declarant\.custody_entities/g, 'las entidades de custodia de tus datos de declarante'],
    [/tax_declarant\.custody/g, 'la custodia por partida de tus datos de declarante'],
    [/'?\bcustody_entities\b'?/g, 'las entidades de custodia'],
    [/'?\bcustody_country\b'?/g, 'el país de custodia'],
    [/'?\bfirst_acquisition_dates\b'?(?:\.\.\.)?/g, 'las fechas de primera adquisición'],
    [/'?\bprevious_year_isins\b'?/g, 'los ISIN del ejercicio anterior'],
    [/'?\bdeclaracion_anterior\b'?/g, 'la declaración anterior'],
    [/'?\bfiled_720_before\b'?/g, 'si presentaste el 720 antes'],
    [/'?\btelefono\b'?/g, 'el teléfono'],
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
    [/\bSIN_DATOS\b/g, 'N/D'],
];

export function humanizeTaxText(text: string): string {
    return REPLACEMENTS.reduce((acc, [pattern, value]) => acc.replace(pattern, value), text);
}
