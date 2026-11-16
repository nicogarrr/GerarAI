import{describe,it,expect}from'vitest';import{render,screen}from'@testing-library/react';
import{UnifiedStateNotice,UNIFIED_REASON_KEYS,UNIFIED_ELIGIBILITY_KEYS,unifiedMissingLabel}from'@/components/proPicks/unified/UnifiedStateNotice';
import{createTranslator}from'@/lib/i18n/translate';
import{writeFileSync,mkdirSync}from'node:fs';
describe('unified truthful notices',()=>{
 it('exposes eligibility labels and a nonnumeric missing label',()=>{const t=createTranslator('es');expect(Object.keys(UNIFIED_ELIGIBILITY_KEYS)).toHaveLength(4);expect(unifiedMissingLabel(t)).toBe('No disponible')});
 it.each(['es','en']as const)('%s covers all states without invented data',locale=>{
 const t=createTranslator(locale);const{container,rerender}=render(<UnifiedStateNotice t={t} state="ok"/>);expect(container.textContent).toBe('');
 for(const state of['empty','partial','error','stale','retained']as const){rerender(<UnifiedStateNotice t={t} state={state} asOf="2026-11-13" affectedBlocks={['DCA']}/>);expect(container.textContent).not.toMatch(/0%|50\/100|0\/100/);expect(screen.getByText(t(`propicks.unifiedStates.states.${state}`))).toBeTruthy();}
 });
 it.each(Object.keys(UNIFIED_REASON_KEYS))('%s has a specific nonnumeric explanation',code=>{const t=createTranslator('es');const{container}=render(<UnifiedStateNotice t={t} state="partial" reasonCodes={[code,code]}/>);const key=UNIFIED_REASON_KEYS[code as keyof typeof UNIFIED_REASON_KEYS];expect(screen.getAllByText(t(key))).toHaveLength(1);expect(container.textContent).not.toMatch(/0%|50\/100/)});
 it.each(['timeout','unauthenticated','forbidden','rate_limited','unavailable','invalid_response']as const)('error %s is not empty',errorKind=>{const t=createTranslator('es');render(<UnifiedStateNotice t={t} state="error" errorKind={errorKind} retryAfterSeconds={12}/>);expect(screen.getByRole('alert')).toBeTruthy();expect(screen.queryByText(t('propicks.unifiedStates.states.empty'))).toBeNull();expect(screen.getByText(t(`propicks.unifiedStates.errors.${errorKind}`))).toBeTruthy();});
 it('unknown reasons remain visible as unverified, not raw service prose',()=>{render(<UnifiedStateNotice t={createTranslator('es')} state="partial" reasonCodes={['secret upstream']} retryAfterSeconds={NaN}/>);expect(screen.getByText('Hay un dato pendiente de verificar.')).toBeTruthy();expect(document.body.textContent).not.toContain('secret upstream');});
 it.each(['es','en']as const)('exports %s actual notice component',locale=>{const t=createTranslator(locale);const{container}=render(<main className="mx-auto max-w-5xl space-y-4 p-4"><p>ProPicks · QA fixture</p>{(['empty','partial','error','stale','retained']as const).map(state=><UnifiedStateNotice key={state} t={t} state={state} asOf="2026-11-13" errorKind={state==='error'?'timeout':undefined} reasonCodes={state==='partial'?['price_missing','valuation_disputed']:[]}/>)}</main>);mkdirSync('/tmp/unified-states-visuals',{recursive:true});writeFileSync(`/tmp/unified-states-visuals/${locale}.html`,container.innerHTML);});
});


it.each(['empty', 'partial', 'error'] as const)('does not print a fixed source date in %s', state => {
 const {container}=render(<UnifiedStateNotice t={createTranslator('es')} state={state} asOf="2026-11-13"/>);
 expect(container.textContent).not.toContain('2026-11-13');
});
it.each(['stale', 'retained'] as const)('keeps the date inside a %s data warning', state => {
 const {container}=render(<UnifiedStateNotice t={createTranslator('es')} state={state} asOf="2026-11-13"/>);
 expect(container.textContent).toContain('2026-11-13');
});
it.each(['constructor', 'toString', '__proto__'])('inherited reason %s uses the neutral explanation',code=>{
 render(<UnifiedStateNotice t={createTranslator('es')} state="partial" reasonCodes={[code]}/>);
 expect(screen.getByText('Hay un dato pendiente de verificar.')).toBeTruthy();
});

it('translates contract block identifiers instead of exposing raw API words',()=>{
 const t=createTranslator('es');render(<UnifiedStateNotice t={t} state="partial" affectedBlocks={['valuation']}/>);
 expect(screen.getByText(t('propicks.unified.colValuation'))).toBeTruthy();
});
