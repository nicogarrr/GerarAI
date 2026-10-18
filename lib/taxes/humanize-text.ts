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
    [/clave\s+'?tax_declarant'?/g, 'los datos del declarante'],
    [/'?\btax_declarant\b'?/g, 'los datos del declarante'],
    [/'?\bcustody\b'?/g, 'la custodia por partida'],
    [/\bmetadata del tenant\b/g, 'tus datos fiscales'],
    [/\bdel tenant\b/g, 'de tu cuenta'],
    [/\bSIN_DATOS\b/g, 'N/D'],
];

export function humanizeTaxText(text: string): string {
    return REPLACEMENTS.reduce((acc, [pattern, value]) => acc.replace(pattern, value), text);
}
