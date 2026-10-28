import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CompanyLogo } from '@/components/calendar/CompanyLogo';

type Px = { w: number; h: number; data: Uint8ClampedArray };
let pixels: Px;
let ctxAvailable = true;
let drawCalls: unknown[][] = [];

function solid(w: number, h: number, rgba: [number, number, number, number], paint?: (d: Uint8ClampedArray, w: number) => void): Px {
    const data = new Uint8ClampedArray(w * h * 4);
    for (let i = 0; i < w * h; i++) data.set(rgba, i * 4);
    paint?.(data, w);
    return { w, h, data };
}

beforeEach(() => {
    ctxAvailable = true;
    drawCalls = [];
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((() =>
        ctxAvailable
            ? {
                  drawImage: (...a: unknown[]) => drawCalls.push(a),
                  getImageData: () => ({ data: pixels.data }),
              }
            : null) as never);
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,CROP');
});
afterEach(() => vi.restoreAllMocks());

function loaded(img: HTMLImageElement, naturalWidth: number, naturalHeight: number) {
    Object.defineProperty(img, 'naturalWidth', { value: naturalWidth, configurable: true });
    Object.defineProperty(img, 'naturalHeight', { value: naturalHeight, configurable: true });
    fireEvent.load(img);
}
const getImg = (c: HTMLElement) => c.querySelector('img') as HTMLImageElement;

describe('CompanyLogo', () => {
    it('ticker vacío: iniciales, sin <img>', () => {
        const { container } = render(<CompanyLogo ticker=" " name="Acme Corp" />);
        expect(container.querySelector('img')).toBeNull();
        expect(container.textContent).toMatch(/A/);
    });
    it('empieza por la fuente FMP codificada y muestra iniciales mientras carga', () => {
        const { container } = render(<CompanyLogo ticker="CGEO.L" name="Georgia" />);
        expect(getImg(container).src).toBe('https://financialmodelingprep.com/image-stock/CGEO.L.png');
        expect(getImg(container).className).toContain('opacity-0');
        expect(container.textContent).not.toBe('');
    });
    it('error de carga: pasa a /api/logo y, si también falla, a las iniciales', () => {
        const { container } = render(<CompanyLogo ticker="AENA" name="Aena" />);
        fireEvent.error(getImg(container));
        expect(getImg(container).getAttribute('src')).toBe('/api/logo/AENA');
        fireEvent.error(getImg(container));
        expect(container.querySelector('img')).toBeNull();
        expect(container.textContent).toMatch(/A/);
    });
    it('imagen de 0 px de ancho se considera rota y salta a la siguiente fuente', () => {
        const { container } = render(<CompanyLogo ticker="X" name="X Corp" />);
        loaded(getImg(container), 0, 0);
        expect(getImg(container).getAttribute('src')).toBe('/api/logo/X');
    });
    it('placeholder en blanco: siguiente fuente (nunca un hueco vacío)', () => {
        pixels = solid(8, 8, [255, 255, 255, 255]);
        const { container } = render(<CompanyLogo ticker="BLNK" name="Blank" />);
        loaded(getImg(container), 8, 8);
        expect(getImg(container).getAttribute('src')).toBe('/api/logo/BLNK');
    });
    it('logo que llena la caja se muestra tal cual con el color de su esquina', () => {
        pixels = solid(8, 8, [10, 10, 200, 255]);
        const { container } = render(<CompanyLogo ticker="FULL" name="Full" />);
        loaded(getImg(container), 8, 8);
        const img = getImg(container);
        expect(img.src).toBe('https://financialmodelingprep.com/image-stock/FULL.png');
        expect(img.className).toContain('object-contain');
        expect(img.className).not.toContain('opacity-0');
        // logo opaco a sangre: rellena con el color de su propia esquina, no con marco blanco
        expect(img.parentElement!.style.background).toBe('rgb(10, 10, 200)');
    });
    it('margen blanco horneado: recorta a la caja de contenido (data URL)', () => {
        pixels = solid(20, 20, [255, 255, 255, 255], (d, w) => {
            for (let y = 8; y < 12; y++) for (let x = 8; x < 12; x++) d.set([200, 0, 0, 255], (y * w + x) * 4);
        });
        const { container } = render(<CompanyLogo ticker="CROP" name="Crop" />);
        loaded(getImg(container), 20, 20);
        expect(getImg(container).getAttribute('src')).toBe('data:image/png;base64,CROP');
    });
    it('el recorte guardado como data URL no supera 128 px de lado (Lighthouse: imágenes sobredimensionadas)', () => {
        // Logo de 1000x500 con margen blanco horneado: el lienzo de análisis es
        // de 256x128 y el contenido ocupa casi todo. El data URL debe salir a
        // tamaño de pantalla (<= 128 px), no al del lienzo de análisis.
        pixels = solid(256, 128, [255, 255, 255, 255], (d, w) => {
            for (let y = 4; y < 124; y++) for (let x = 4; x < 252; x++) d.set([0, 90, 200, 255], (y * w + x) * 4);
        });
        let dataUrlCanvas: { width: number; height: number } | null = null;
        vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(function (this: HTMLCanvasElement) {
            dataUrlCanvas = { width: this.width, height: this.height };
            return 'data:image/png;base64,CROP';
        });
        const { container } = render(<CompanyLogo ticker="WIDE" name="Wide" />);
        loaded(getImg(container), 1000, 500);
        expect(getImg(container).getAttribute('src')).toBe('data:image/png;base64,CROP');
        expect(dataUrlCanvas).not.toBeNull();
        const out = dataUrlCanvas as unknown as { width: number; height: number };
        expect(Math.max(out.width, out.height)).toBeLessThanOrEqual(128);
        // conserva la proporción del recorte (248x120 -> 128x62)
        expect(out.width / out.height).toBeCloseTo(248 / 120, 1);
        const last = drawCalls[drawCalls.length - 1];
        expect(last.slice(5)).toEqual([0, 0, out.width, out.height]);
    });
    it('glifo blanco sobre transparente: se pinta sobre fondo oscuro', () => {
        pixels = solid(10, 10, [0, 0, 0, 0], (d, w) => {
            for (let y = 3; y < 8; y++) for (let x = 3; x < 8; x++) d.set([255, 255, 255, 255], (y * w + x) * 4);
        });
        const { container } = render(<CompanyLogo ticker="UBER" name="Uber" />);
        loaded(getImg(container), 10, 10);
        const wrapper = getImg(container).parentElement!;
        expect(wrapper.style.background).toBe('rgb(24, 24, 27)');
        expect(wrapper.className).not.toContain('bg-white');
    });
    it('sin contexto 2D: se muestra la imagen tal cual, sin iniciales encima', () => {
        ctxAvailable = false;
        const { container } = render(<CompanyLogo ticker="NOCTX" name="No Ctx" />);
        loaded(getImg(container), 8, 8);
        expect(getImg(container).className).not.toContain('opacity-0');
        expect(getImg(container).src).toContain('NOCTX');
    });
    it('canvas contaminado (excepción al leer píxeles): degrada a la imagen tal cual', () => {
        vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((() => ({
            drawImage() {},
            getImageData() { throw new Error('tainted'); },
        })) as never);
        const { container } = render(<CompanyLogo ticker="TAINT" name="Taint" />);
        loaded(getImg(container), 8, 8);
        expect(getImg(container).className).not.toContain('opacity-0');
    });
    it('imagen ya cargada (cache) se analiza al montar y, si todas son blancas, cae a iniciales', () => {
        pixels = solid(8, 8, [255, 255, 255, 255]);
        vi.spyOn(HTMLImageElement.prototype, 'complete', 'get').mockReturnValue(true);
        vi.spyOn(HTMLImageElement.prototype, 'naturalWidth', 'get').mockReturnValue(8);
        vi.spyOn(HTMLImageElement.prototype, 'naturalHeight', 'get').mockReturnValue(8);
        const { container } = render(<CompanyLogo ticker="CACHE" name="Cache" />);
        // en blanco en las dos fuentes: iniciales, nunca un hueco ni logo ajeno
        expect(container.querySelector('img')).toBeNull();
    });
    it('al cambiar de ticker reinicia la cadena de fuentes', () => {
        const { container, rerender } = render(<CompanyLogo ticker="AAA" name="A" />);
        fireEvent.error(getImg(container));
        expect(getImg(container).getAttribute('src')).toBe('/api/logo/AAA');
        rerender(<CompanyLogo ticker="BBB" name="B" />);
        expect(getImg(container).src).toBe('https://financialmodelingprep.com/image-stock/BBB.png');
    });
    it('className llega al contenedor', () => {
        const { container } = render(<CompanyLogo ticker="CLS" name="C" className="size-9" />);
        expect(container.firstElementChild!.className).toContain('size-9');
        void screen;
    });
});
