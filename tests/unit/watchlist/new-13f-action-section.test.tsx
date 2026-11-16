import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { LocaleProvider } from '@/lib/i18n/client';
import { createTranslator } from '@/lib/i18n/translate';
import { mkdirSync, writeFileSync } from 'node:fs';
const m=vi.hoisted(()=>({auth:vi.fn(),request:vi.fn()}));
vi.mock('@/lib/auth/require-user',()=>({requireAuthenticatedUser:m.auth}));
vi.mock('@/lib/research/client',()=>({researchRequest:m.request}));
import { getWatchlistNew13f } from '@/lib/actions/watchlist-new-13f.actions';
import New13fSection from '@/components/watchlist/New13fSection';
const holder={cik:'one',name:'Example Fund',shares:10,value_usd:null};
const item={ticker:'BRK/B',status:'ok',period:'2026-09-30',new_positions:{status:'valor_parcial',count:1,value_known_count:0,top_by_shares:[holder],top_by_value:[]}};
beforeEach(()=>{vi.clearAllMocks();vi.spyOn(console,'error').mockImplementation(()=>{});m.auth.mockResolvedValue({id:'u1'});});
describe('new 13F action boundaries',()=>{
 it('authenticates and reads only the tenant-scoped endpoint',async()=>{m.request.mockResolvedValue({items:[item]});expect(await getWatchlistNew13f()).toEqual({data:[item],unavailable:false});expect(m.auth).toHaveBeenCalled();expect(m.request).toHaveBeenCalledWith('/api/watchlist/new-13f');});
 it('keeps a truly empty watchlist distinct from failure',async()=>{m.request.mockResolvedValue({items:[]});expect(await getWatchlistNew13f()).toEqual({data:[],unavailable:false});});
 it.each([null,{}, {items:null},{items:[{...item,new_positions:{...item.new_positions,count:NaN}}]},{items:[{...item,new_positions:{...item.new_positions,top_by_shares:[{...holder,shares:Infinity}]}}]},{items:[{...item,new_positions:{...item.new_positions,top_by_shares:null}}]}])('malformed payload %# is unavailable',async payload=>{m.request.mockResolvedValue(payload);expect(await getWatchlistNew13f()).toEqual({data:null,unavailable:true});});
 it('does not call the service after authentication fails',async()=>{m.auth.mockRejectedValue(Error('no session'));expect(await getWatchlistNew13f()).toEqual({data:null,unavailable:true});expect(m.request).not.toHaveBeenCalled();});
 it('distinguishes downstream failure from no positions',async()=>{m.request.mockRejectedValue(Error('offline'));expect(await getWatchlistNew13f()).toEqual({data:null,unavailable:true});});
});
describe('streamed new 13F section',()=>{
 const t=createTranslator('es');
 it('does not render an empty watchlist',async()=>{expect(await New13fSection({t,promise:Promise.resolve({data:[],unavailable:false})})).toBeNull();});
 it('shows an honest service error instead of vanishing',async()=>{const html=renderToStaticMarkup(await New13fSection({t,promise:Promise.resolve({data:null,unavailable:true})}));expect(html).toContain(t('watchlist.new13f.unavailable'));expect(html).toContain('role="status"');});
 it('encodes ticker links and renders partial declared values',async()=>{const html=renderToStaticMarkup(await New13fSection({t,promise:Promise.resolve({data:[item],unavailable:false})}));expect(html).toContain('/research/BRK%2FB');expect(html).toContain('Example Fund');expect(html).toContain('N/D');expect(html).toContain(t('watchlist.new13f.partial'));});
 it.each(['es','en'] as const)('exports %s real panel for visual inspection',async locale=>{const panel=await New13fSection({t:createTranslator(locale),promise:Promise.resolve({data:[item],unavailable:false})});const html=renderToStaticMarkup(<LocaleProvider locale={locale}>{panel}</LocaleProvider>);expect(html).toContain(createTranslator(locale)('watchlist.new13f.sharesSuffix'));mkdirSync('/tmp/watch13f-visual',{recursive:true});writeFileSync(`/tmp/watch13f-visual/${locale}.html`,html);});
});
