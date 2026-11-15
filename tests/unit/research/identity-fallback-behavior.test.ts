import { describe, expect, it } from 'vitest';
import { looksLikeTicker } from '@/lib/research/ticker-shape';
import { resolveUnknownListingIdentity } from '@/lib/research/unknown-listing';
import type { FinnhubProfile2 } from '@/lib/actions/finnhub.actions';
import { fetchInBatches } from '@/lib/research/snapshots';
import { engineNoticeText } from '@/lib/research/engine-notice';
describe('unknown ticker identity is never fabricated from a provider name',()=>{
    it('distinguishes provider outage, unknown symbol and unverified issuer identity',()=>{expect(resolveUnknownListingIdentity(null,'ALM')).toEqual({kind:'unavailable'});for(const name of [undefined,'','  ',' alm '])expect(resolveUnknownListingIdentity({name} as FinnhubProfile2,'ALM')).toEqual({kind:'not-in-sources'});expect(resolveUnknownListingIdentity({name:' Almonty US '} as FinnhubProfile2,'ALM')).toEqual({kind:'unverified',providerName:'Almonty US'});});
    it.each(['MSFT','SAN.MC','BRK-B','^GSPC','EURUSD=X','GC=F',' aapl '])('accepts plausible ticker %s without treating it as verified identity',value=>{expect(looksLikeTicker(value)).toBe(true);});
    it.each(['settings','%E0','a/b','','verylongticker'])('rejects routes and malformed symbols %s',value=>{expect(looksLikeTicker(value)).toBe(false);});
});
describe('snapshot batch failure only degrades the failed batch',()=>{
    it('launches ordered batches and keeps other snapshots when one source call fails',async()=>{const calls:string[][]=[];expect(await fetchInBatches(['A','B','C','D','E'],2,async batch=>{calls.push(batch);if(batch.includes('C'))throw new Error('offline');return batch.join(',');})).toEqual(['A,B',null,'E']);expect(calls).toEqual([['A','B'],['C','D'],['E']]);expect(await fetchInBatches([],2,async()=>1)).toEqual([]);await expect(fetchInBatches(['A'],0,async()=>1)).rejects.toThrow('batchSize');});
    it('labels indicative or unsourced output without rewriting unknown notices',()=>{expect(engineNoticeText('INDICATIVE RANGE - fixture')).toMatch(/RANGO INDICATIVO/);expect(engineNoticeText('Valuation computed from defaults')).toMatch(/fuente/);expect(engineNoticeText('Future warning')).toBe('Future warning');expect(engineNoticeText('INDICATIVE RANGE - fixture','en')).toBe('INDICATIVE RANGE - fixture');});
});
