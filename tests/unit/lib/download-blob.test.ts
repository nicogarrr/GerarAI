// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { downloadBlob } from '@/lib/download-blob';

afterEach(() => vi.restoreAllMocks());

describe('downloadBlob', () => {
    it('downloads the original bytes and filename, then removes and revokes the temporary link', () => {
        const blob = new Blob([new Uint8Array([0, 127, 255])], { type: 'application/octet-stream' });
        const create = vi.fn(() => 'blob:test');
        const revoke = vi.fn();
        vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke });
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            expect(this.download).toBe('modelo-720.txt');
            expect(this.href).toBe('blob:test');
            expect(document.body.contains(this)).toBe(true);
            expect(revoke).not.toHaveBeenCalled();
        });
        try {
            downloadBlob('modelo-720.txt', blob);
            expect(create).toHaveBeenCalledWith(blob);
            expect(click).toHaveBeenCalledOnce();
            expect(document.body.querySelector('a')).toBeNull();
            expect(revoke).toHaveBeenCalledWith('blob:test');
        } finally {
            vi.unstubAllGlobals();
        }
    });
});
