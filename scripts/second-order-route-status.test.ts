import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
// @ts-expect-error explicit TS extension
import {AppError} from '../lib/types/errors.ts';
function handler(error?: unknown) {
 const code=ts.transpileModule(readFileSync('app/api/news/[eventId]/second-order/route.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
 const context={exports:{},require:(name:string)=>{
  if(name==='next/server')return {NextResponse:{json:(body:unknown,options?:{status:number})=>({body,status:options?.status??200})}};
  if(name.includes('route-auth'))return {withAuthErrors:(fn:unknown)=>fn};
  if(name.includes('require-user'))return {requireAuthenticatedUser:async()=>({id:'test'})};
  if(name.includes('types/errors'))return {AppError};
  if(name.includes('research/client'))return {researchRequest:async()=>{if(error)throw error;return {status:'sin_datos'};}};
  throw new Error(name);
 }};
 vm.runInNewContext(code,context);
 return (context.exports as {GET:(r:unknown,p:{params:Promise<{eventId:string}>})=>Promise<{status:number;body:unknown}>}).GET;
}
test('tenant missing/other-tenant upstream404 stays clean404 not502',async()=>{
 const result=await handler(new AppError('private upstream text','RESEARCH_API_ERROR',404))(null,{params:Promise.resolve({eventId:'156016'})});
 assert.equal(result.status,404);
 assert.equal(JSON.stringify(result.body),JSON.stringify({status:'not_found',detail:'Noticia no encontrada'}));
});
test('transport failure remains502; success and invalid id unchanged',async()=>{
 const params={params:Promise.resolve({eventId:'5'})};
 assert.equal((await handler(new Error('timeout'))(null,params)).status,502);
 assert.equal((await handler()(null,params)).status,200);
 assert.equal((await handler()(null,{params:Promise.resolve({eventId:'invalid'})})).status,400);
});
