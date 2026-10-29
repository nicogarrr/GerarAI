/**
 * Inputs inferidos: el formato lo manda la unidad declarada, nunca la clave ni la magnitud.
 * Ejecución: node --experimental-strip-types --test scripts/provenance-format-guard.test.ts
 */
import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { capitalizeLabel, formatProvenanceValue } from "../lib/research/provenance-format.ts"

describe("formatProvenanceValue", () => {
    it("unidad decimal/ratio: fracción a porcentaje, incluido más de 100 %", () => {
        assert.match(formatProvenanceValue(0.1442999, "decimal"), /^14,4\s?%$/)
        assert.match(formatProvenanceValue(1.5, "decimal"), /^150,0\s?%$/)
        assert.match(formatProvenanceValue(1, "ratio"), /^100,0\s?%$/)
    })
    it("unidad %: ya es porcentaje, no se multiplica", () => {
        assert.match(formatProvenanceValue(25, "%"), /^25,0\s?%$/)
        assert.match(formatProvenanceValue(1.5, "%"), /^1,5\s?%$/)
    })
    it("importe en la divisa declarada (USD y no USD)", () => {
        assert.equal(formatProvenanceValue(4869930000, "USD"), "4,87 mil M\u00a0US$")
        assert.equal(formatProvenanceValue(14.4, "USD"), "14,40\u00a0US$")
        assert.match(formatProvenanceValue(2500000000, "EUR"), /^2,50 mil M\u00a0€$/)
    })
    it("sin unidad declarada: número sin símbolo ni %, también para shares_* y penetration", () => {
        const shares = formatProvenanceValue(255982592, null)
        assert.ok(!shares.includes("%") && !shares.includes("$"), shares)
        for (const v of [1, 1.2, 25, 0.5]) {
            const out = formatProvenanceValue(v, undefined)
            assert.ok(!/[%$€]/.test(out), out)
        }
    })
    it("otra unidad: número + unidad", () => {
        assert.equal(formatProvenanceValue(45, "shares"), "45 acciones")
        assert.equal(formatProvenanceValue(12, "satélites"), "12 satélites")
    })
    it("pure y unidades adimensionales: sin sufijo técnico", () => {
        for (const unit of ["pure", "unitless", "dimensionless"]) assert.equal(formatProvenanceValue(1.25, unit), "1,25")
    })
    it("sin dato es N/D", () => {
        assert.equal(formatProvenanceValue(null, "USD"), "N/D")
    })
    it("no adivina por el nombre de la clave: la firma no recibe la clave", () => {
        const src = readFileSync("lib/research/provenance-format.ts", "utf8")
        assert.doesNotMatch(src, /_HINT|test\(key\)/)
    })
    it("capitalizeLabel", () => {
        assert.equal(capitalizeLabel("suscriptores direccionables"), "Suscriptores direccionables")
    })
})

describe("ThesisMemo", () => {
    const src = readFileSync("components/research/ThesisMemo.tsx", "utf8")
    it("pinta la etiqueta en español, no item.key crudo", () => {
        assert.match(src, /metricLabel\(item\.key\)/)
        assert.doesNotMatch(src, />\{item\.key\}</)
    })
    it("formatea con el valor y la unidad del input", () => {
        assert.match(src, /formatProvenanceValue\(item\.value, item\.unit\)/)
    })
})

describe('unidades en inglés', () => { it('count y USD_per_unit nunca se pintan crudas', () => {
  assert.equal(formatProvenanceValue(9, 'count'), '9');
  assert.match(formatProvenanceValue(12.5, 'USD_per_unit'), /USD por unidad$/);
}); })
