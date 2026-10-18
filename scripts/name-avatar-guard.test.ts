/**
 * Avatares sin foto: color estable por nombre e iniciales correctas.
 * Ejecución: node --experimental-strip-types --test scripts/name-avatar-guard.test.ts
 */
import { describe, it } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { AVATAR_TONES, avatarInitials, avatarTone } from "../lib/ui/avatar-color.ts"

describe("avatar sin foto", () => {
    it("el color es estable y no depende de mayúsculas ni espacios", () => {
        assert.equal(avatarTone("Warren Buffett"), avatarTone("  warren buffett "))
        assert.ok((AVATAR_TONES as readonly string[]).includes(avatarTone("Michael Burry")))
    })
    it("nombres distintos reparten color (no todos iguales)", () => {
        const names = ["Buffett", "Ackman", "Tepper", "Bezos", "Munger", "Burry", "Dalio", "Klarman"]
        assert.ok(new Set(names.map(avatarTone)).size >= 3)
    })
    it("iniciales: primera y última palabra, sin nombre es ?", () => {
        assert.equal(avatarInitials("Warren Edward Buffett"), "WB")
        assert.equal(avatarInitials("ackman"), "A")
        assert.equal(avatarInitials("   "), "?")
        assert.equal(avatarInitials("Álvaro Ñ"), "ÁÑ")
        // QA 22: el paréntesis de «Harris Associates (Oakmark)» no es una inicial.
        assert.equal(avatarInitials("Harris Associates (Oakmark)"), "HO")
    })
    it("InvestorAvatar usa NameAvatar, no un círculo propio con color fijo", () => {
        const src = readFileSync("app/(root)/inversores/_components/Avatar.tsx", "utf8")
        assert.match(src, /NameAvatar/)
        assert.doesNotMatch(src, /bg-lime-400/)
    })
})
