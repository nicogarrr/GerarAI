import {describe,expect,it} from 'vitest';
import {cleanThesisText,cleanThesisMarkdown,localizeMemoNumbers} from '@/lib/research/thesis-text';
describe('source-preserving thesis presentation',()=>{
 it('preserves full URL while translating adjacent metrics',()=>{
  const url='https://x.com/a?utm_source=n&ref_id=2&value=1.234567';
  const text=cleanThesisText(`roe_ttm: ${url}`);
  expect(text).toContain(url);expect(text.split(': ')[0]).not.toContain('_');
 });
 it('does not shift a zone-free calendar timestamp into tomorrow',()=>{
  expect(localizeMemoNumbers('2026-11-16T23:30:00')).toBe('16 nov 2026');
  expect(localizeMemoNumbers('2026-11-16T23:30:00Z')).toBe('17 nov 2026');
 });
 for(const clean of [cleanThesisText,cleanThesisMarkdown]){
  it('keeps None as prose and quoted source, localizing only missing tokens',()=>{
   expect(clean('"None of the above"')).toBe('"None of the above"');
   expect(clean('None of the above')).toBe('None of the above');
   expect(clean('ROE: None')).toBe('ROE: N/D');
   expect(clean('None')).toBe('N/D');
  });
 }
});
