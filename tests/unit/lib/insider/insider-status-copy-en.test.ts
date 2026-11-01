import { describe, expect, it } from 'vitest';
import { analyzedCountCopy, degradedCopy, durableReadCopy, persistedSourceCopy, reasonCopy } from '@/lib/insider-status-copy';

const n = (v: unknown) => (typeof v === 'number' ? v.toLocaleString('en-US') : '?');

describe('insider-status-copy en inglés', () => {
    it('estado degradado con contadores y con razón', () => {
        expect(degradedCopy('AAPL', { filings_scanned: 20, filings_failed: 20 }, n, 'en').header)
            .toBe('AAPL: SEC EDGAR returned no readable Form 4 (20 failed out of 20 scanned).');
        const generic = degradedCopy('AAPL', { reason: 'sec_bloquea_datacenter' }, n, 'en');
        expect(generic.header).toBe("AAPL: the Form 4 signals from SEC EDGAR couldn't be fetched or read.");
        expect(generic.detail).toBe('the SEC rejects automated requests from this server (HTTP 403)');
        expect(reasonCopy('AAPL: TypeError', 'en')).toBeNull();
    });
    it('recuentos, histórico y filings persistidos', () => {
        expect(analyzedCountCopy('partial', { filings_scanned: 1200, filings_parsed: 3 }, n, 'en')).toBe('3 readable of 1,200 scanned');
        expect(analyzedCountCopy('ok', { filings_scanned: 1 }, n, 'en')).toBe('1 analyzed');
        expect(durableReadCopy({ reason: 'x' }, 'en').header).toMatch(/^The history of filings saved by the monitor couldn't be read/);
        expect(persistedSourceCopy('MSFT', { filings_from_persisted: 4, filings_scanned: 6, latest_persisted_filing_date: '2026-10-30' }, n, 'en'))
            .toBe('MSFT: 4 of 6 Form 4s from saved filings (latest filing: 2026-10-30); the live SEC EDGAR read failed. The data comes from those filings, not from today.');
        expect(persistedSourceCopy('MSFT', { filings_from_persisted: 0 }, n, 'en')).toBeNull();
    });
    it('el español no cambia', () => {
        expect(degradedCopy('AAPL', { filings_scanned: 20, filings_failed: 20 }, n).header).toContain('SEC EDGAR no devolvió ningún Form 4 legible');
        expect(analyzedCountCopy('partial', { filings_scanned: 2, filings_parsed: 1 }, n)).toBe('1 legible de 2 escaneados');
    });
});
