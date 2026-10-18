import { describe, it } from "node:test"
import assert from "node:assert/strict"
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { formulaDisplay } from "../lib/research/formula-display.ts"

describe("formulaDisplay", () => {
    it("traduce identificadores y operadores sin inventar términos", () => {
        const out = formulaDisplay("operating_income * (1 - effective_tax_rate) / average(invested_capital)")
        assert.doesNotMatch(out, /_/)
        assert.doesNotMatch(out, /average|\*/)
        assert.match(out, /×/)
        assert.match(out, /÷ media\(/)
    })
    it("vacío si no hay fórmula", () => {
        assert.equal(formulaDisplay(null), "")
    })
})
