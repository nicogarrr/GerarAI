import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { testResultMessage } from '@/components/settings/LlmSettingsForm';
import { createTranslator } from '@/lib/i18n/translate';

// Frases reales de la prueba de conexión (tenant_llm_settings_service.py y
// egress_guard.py), leídas del .py: si el backend las cambia, el test lo nota.
const SERVICE = readFileSync('data-engine/app/services/tenant_llm_settings_service.py', 'utf8');
const GUARD = readFileSync('data-engine/app/llm/egress_guard.py', 'utf8');
const pick = (src: string, re: RegExp): string => {
    const m = src.match(re);
    if (!m) throw new Error(`no encontrado: ${re}`);
    return m[1];
};
const TIMEOUT = pick(SERVICE, /"message": "(El proveedor no respondio en 5 segundos\.)"/);
const UNREACHABLE = pick(SERVICE, /else "(No se pudo conectar con el proveedor\.)"/);
const NON_PUBLIC = pick(GUARD, /PUBLIC_ONLY_MESSAGE = "([^"]+)"/);
const HTTP = pick(SERVICE, /f"(El proveedor respondio HTTP )\{response\.status_code\}\."/) + '502.';
const NO_LIST = pick(SERVICE, /"message": "(El proveedor respondio, pero sin una lista de modelos legible[^"]+)"/);
const MISSING = pick(SERVICE, /f"(El modelo ')\{model\}(?:' no existe)/) + "gpt-x' no existe en este proveedor. Revisa el nombre exacto en su lista de modelos.";
const OK = pick(SERVICE, /"message": "(Conexion correcta\.)"/);

const en = createTranslator('en');
const es = createTranslator('es');
const result = (message: string, status_code: number | null = null) => ({ ok: false, status_code, provider: 'openai', base_url: '', model: 'gpt-x', message });

describe('prueba de conexión de la IA propia: frase del backend en el idioma de la pantalla', () => {
    it.each([
        [TIMEOUT, 'The provider did not answer within 5 seconds.'],
        [UNREACHABLE, 'Could not connect to the provider.'],
        [NON_PUBLIC, "The provider URL points to a non-public address."],
        [HTTP, 'The provider answered HTTP 502.'],
        [NO_LIST, "The provider answered, but without a readable model list: the model could not be checked."],
        [MISSING, "The model 'gpt-x' does not exist at this provider. Check the exact name in its model list."],
        [OK, 'Connection OK.'],
    ])('en inglés, «%s»', (spanish, english) => {
        expect(testResultMessage(result(spanish, spanish === HTTP ? 502 : null), en)).toBe(english);
    });

    it('en castellano sale con tildes, y el modelo y el código se conservan', () => {
        expect(testResultMessage(result(OK), es)).toBe('Conexión correcta.');
        expect(testResultMessage(result(HTTP, 502), es)).toBe('El proveedor respondió HTTP 502.');
        expect(testResultMessage(result(MISSING), es)).toBe("El modelo 'gpt-x' no existe en este proveedor. Revisa el nombre exacto en su lista de modelos.");
    });

    it('una frase que no se reconoce pasa tal cual', () => {
        expect(testResultMessage(result('Otra cosa.'), en)).toBe('Otra cosa.');
    });
});
