// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
    insiderCodeLabel, insiderName, insiderRole, isInstitutionalInsiderName,
    signalLabel, signalTooltip, sideLabel,
} from '@/lib/insider/format';

describe('insiderName', () => {
    it('pasa «APELLIDO NOMBRE» de la SEC a «Apellido Nombre»', () => {
        expect(insiderName('SMITH JOHN')).toBe('Smith John');
    });
    it('respeta separadores / y guion', () => {
        expect(insiderName('GARCÍA/LÓPEZ ANA-MARÍA')).toBe('García/López Ana-María');
    });
    it('mayúscula tras apóstrofo: O\'BRIEN -> O\'Brien', () => {
        expect(insiderName("O'BRIEN DEIRDRE")).toBe("O'Brien Deirdre");
        expect(insiderName('D’ANGELO MARK')).toBe('D’Angelo Mark');
    });
    it('no toca un nombre que ya viene en minúsculas/mezcla', () => {
        expect(insiderName('John Smith')).toBe('John Smith');
        expect(insiderName('McDonald')).toBe('McDonald');
    });
    it('vacío o ausente: guion', () => {
        expect(insiderName('')).toBe('—');
        expect(insiderName(null)).toBe('—');
        expect(insiderName('   ')).toBe('—');
    });
});

describe('insiderRole: presidencia del consejo', () => {
    it('traduce Executive Chair/Chairman y Chair', () => {
        expect(insiderRole('Officer, Director', 'Executive Chair')).toContain('Presidente ejecutivo');
        expect(insiderRole('Director', 'Executive Chairman')).toContain('Presidente ejecutivo');
        expect(insiderRole('Director', 'Chairman')).toContain('Presidente del consejo');
    });
    it('Vice Chair se queda como el original (no se rebaja ni inventa)', () => {
        expect(insiderRole('Officer', 'Vice Chair')).toContain('Vice Chair');
    });
});

describe('insiderRole', () => {
    it('traduce siglas seguras', () => {
        expect(insiderRole('officer', 'CEO')).toBe('CEO');
        expect(insiderRole('officer', 'CFO')).toBe('CFO');
        expect(insiderRole('officer', 'Chief Financial Officer')).toBe('CFO');
    });
    it('compone cargos múltiples en orden de aparición', () => {
        expect(insiderRole('officer', 'President and CEO')).toBe('Presidente y CEO');
    });
    it('NO traduce siglas ambiguas (CRO puede ser riesgos o ingresos): se muestra cruda', () => {
        expect(insiderRole('officer', 'CRO')).toBe('CRO');
    });
    it('un título con resto sin mapear se muestra original: nunca rebaja el cargo', () => {
        expect(insiderRole('officer', 'Vice President, Global Sales')).toBe('Vice President, Global Sales');
        expect(insiderRole('officer', 'Assistant Secretary')).toBe('Assistant Secretary');
    });
    it('Senior/Executive VP no disparan también Vicepresidente suelto', () => {
        expect(insiderRole('officer', 'Senior Vice President')).toBe('Vicepresidente senior');
        expect(insiderRole('officer', 'Executive Vice President')).toBe('Vicepresidente ejecutivo');
    });
    it('rol director y 10% owner', () => {
        expect(insiderRole('director', null)).toBe('Director');
        expect(insiderRole('10% owner', null)).toBe('Accionista 10 %');
    });
    it('combinación de cargos y roles se une con ·', () => {
        expect(insiderRole('officer, director', 'CEO')).toBe('CEO · Director');
    });
    it('multiple insiders y desconocido', () => {
        expect(insiderRole('multiple insiders', null)).toBe('Varios insiders');
        expect(insiderRole(null, null)).toBe('Insider');
        expect(insiderRole('officer', null)).toBe('Directivo');
    });
});

describe('sideLabel / insiderCodeLabel', () => {
    it('compra/venta y guion', () => {
        expect(sideLabel('compra')).toBe('Compra');
        expect(sideLabel('venta')).toBe('Venta');
        expect(sideLabel('otro')).toBe('—');
    });
    it('con traductor usa las claves i18n (EN: Buy/Sell)', () => {
        const en = ((path: string) =>
            path === 'insider.feed.sideBuyLabel' ? 'Buy' : path === 'insider.feed.sideSellLabel' ? 'Sell' : path) as never;
        expect(sideLabel('compra', en)).toBe('Buy');
        expect(sideLabel('venta', en)).toBe('Sell');
        expect(sideLabel('otro', en)).toBe('—');
        expect(insiderCodeLabel('P', en)).toBe('Buy');
        expect(insiderCodeLabel('S', en)).toBe('Sell');
    });
    it('P y S se tratan como compra/venta; el resto se traduce; desconocido se muestra crudo', () => {
        expect(insiderCodeLabel('P')).toBe('Compra');
        expect(insiderCodeLabel('S')).toBe('Venta');
        expect(insiderCodeLabel('M')).toBe('Ejercicio de opción');
        expect(insiderCodeLabel('f')).toBe('Retención fiscal'); // case-insensitive
        expect(insiderCodeLabel('Z')).toBe('Código Z');
        expect(insiderCodeLabel('')).toBe('—');
        expect(insiderCodeLabel(null)).toBe('—');
    });
});

describe('isInstitutionalInsiderName', () => {
    it('detecta entidades (Inc, LLC, fondos...) que no son insiders personales', () => {
        expect(isInstitutionalInsiderName('Berkshire Hathaway Inc')).toBe(true);
        expect(isInstitutionalInsiderName('Vanguard Group')).toBe(true);
        expect(isInstitutionalInsiderName('John Smith')).toBe(false);
        expect(isInstitutionalInsiderName(null)).toBe(false);
    });
});

describe('signalLabel / signalTooltip', () => {
    it('etiquetas conocidas y clave desconocida mostrada cruda (nunca inventada)', () => {
        expect(signalLabel('cluster_buy')).toBe('Cluster de compra');
        expect(signalLabel('nueva_clave_backend')).toBe('nueva_clave_backend');
        expect(signalLabel('')).toBe('—');
    });
    it('tooltip con el umbral real; clave desconocida sin tooltip', () => {
        expect(signalTooltip('big_buy')).toBe('Una compra supera 1 M$');
        expect(signalTooltip('nueva_clave_backend')).toBeUndefined();
        expect(signalTooltip(null)).toBeUndefined();
    });
});

describe('insiderRole: cargos compuestos observados en móvil', () => {
    it('traduce el título completo sin perder relaciones gubernamentales', () => {
        expect(insiderRole('Officer', 'SVP, GC and Government Affairs')).toBe('Vicepresidente senior y Asesor jurídico general y Relaciones gubernamentales');
        expect(insiderRole('Officer', 'Officer')).toBe('Directivo');
    });
    it('no inventa la expansión de CLO ni de divisiones desconocidas', () => {
        expect(insiderRole('Officer, Director', 'CFO and CLO')).toBe('CFO and CLO · Director');
        expect(insiderRole('Officer', 'SVP, Government Affairs Europe')).toBe('SVP, Government Affairs Europe');
    });
});
