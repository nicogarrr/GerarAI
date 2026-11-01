import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LetterReaderPage from '@/app/(root)/inversores/cartas/[id]/page';
const mocks=vi.hoisted(()=>({document:vi.fn(),chunks:vi.fn()}));
vi.mock('@/lib/actions/research-tools.actions',()=>({getKnowledgeDocument:mocks.document,getKnowledgeDocumentChunkPage:mocks.chunks}));
vi.mock('next/link',()=>({default:({children,...props}:React.AnchorHTMLAttributes<HTMLAnchorElement>)=><a {...props}>{children}</a>}));
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>undefined})}));
vi.mock('next/navigation',()=>({notFound:()=>{throw Error('NOT_FOUND');}}));
vi.mock('@/app/(root)/inversores/_components/LibraryChat',()=>({LibraryChat:()=>null}));
vi.mock('@/app/(root)/inversores/_components/Pagination',()=>({Pagination:()=>null}));
vi.mock('@/components/system/BackendOffline',()=>({default:()=>null}));
describe('letter reader breadcrumb',()=>{
 beforeEach(()=>{window.history.replaceState({},'', '/inversores/cartas/987');mocks.chunks.mockResolvedValue([]);});
 it('publishes the loaded title, not a presumed seed ID',async()=>{
  mocks.document.mockResolvedValue({id:987,title:'Carta de prueba 2031',document_type:'fund_letter',chunk_count:0,author:'Autora de prueba'});
  const view=render(await LetterReaderPage({params:Promise.resolve({id:'987'}),searchParams:Promise.resolve({})}));
  expect(mocks.document).toHaveBeenCalledWith(987);
  await waitFor(()=>expect(JSON.parse(document.documentElement.dataset.pageBreadcrumb!)).toEqual({path:'/inversores/cartas/987',name:'Carta de prueba 2031'}));
  view.unmount();expect(document.documentElement.dataset.pageBreadcrumb).toBeUndefined();
 });
 it('rejects non-letter documents without publishing a title',async()=>{
  mocks.document.mockResolvedValue({id:987,title:'Un libro',document_type:'book',chunk_count:0});
  await expect(LetterReaderPage({params:Promise.resolve({id:'987'}),searchParams:Promise.resolve({})})).rejects.toThrow('NOT_FOUND');
  expect(document.documentElement.dataset.pageBreadcrumb).toBeUndefined();
 });
});
