import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {createRequire} from 'node:module';
import vm from 'node:vm';
import ts from 'typescript';
test('library refresh is active-job scoped and cleaned up; completion feedback remains',()=>{
 const page=readFileSync('app/(root)/knowledge/page.tsx','utf8');
 assert.match(page,/ExtractionRefresh active=\{activeJobs.length > 0\}/);
 assert.match(page,/extractionResultText\(job, t\)/);
 const refresh=readFileSync('components/knowledge/ExtractionRefresh.tsx','utf8');
 const code=ts.transpileModule(refresh,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 const timers=new Map<number,{callback:()=>void;delay:number}>();
 let id=0, refreshed=0;
 let cleanup:(()=>void)|undefined;
 const document={visibilityState:'visible'};
 const nativeRequire=createRequire(import.meta.url);
 const context={exports:{},require:(name:string)=>name==='react'?{useEffect:(fn:()=>undefined|(()=>void))=>{cleanup=fn();}}:name==='next/navigation'?{useRouter:()=>({refresh:()=>refreshed++})}:nativeRequire(name),document,
 window:{setTimeout:(callback:()=>void,delay:number)=>{timers.set(++id,{callback,delay});return id;},clearTimeout:(key:number)=>timers.delete(key)}};
 vm.runInNewContext(code,context);
 const render=(context.exports as {ExtractionRefresh:(p:{active:boolean})=>null}).ExtractionRefresh;
 render({active:false}); assert.equal(timers.size,0);
 render({active:true}); assert.equal(timers.size,1); assert.equal(timers.get(id)?.delay,30_000);
 const tick=()=>{const timer=timers.get(id)!;timers.delete(id);timer.callback();};
 tick(); assert.equal(refreshed,1); assert.equal(timers.size,1); assert.equal(timers.get(id)?.delay,60_000);
 document.visibilityState='hidden';tick();assert.equal(refreshed,1);assert.equal(timers.size,1);
 document.visibilityState='visible';tick();assert.equal(refreshed,2);assert.equal(timers.get(id)?.delay,60_000);
 cleanup?.(); assert.equal(timers.size,0);
});
