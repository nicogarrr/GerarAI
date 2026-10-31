import React from 'react';
import {render,screen} from '@testing-library/react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import PaperTradingPage from '@/app/(root)/paper-trading/page';
const mocks=vi.hoisted(()=>({account:vi.fn(),history:vi.fn(),valuation:vi.fn()}));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('next/cache',()=>({revalidatePath:vi.fn()}));
vi.mock('@/lib/actions/manual-demo.actions',()=>({getManualDemoAccount:mocks.account,getManualDemoValuation:mocks.valuation,placeManualOrder:vi.fn(),convertManualDemoCurrency:vi.fn()}));
vi.mock('@/lib/actions/manual-demo-history.actions',()=>({getManualDemoHistory:mocks.history}));
vi.mock('@/components/paper-trading/ManualDemoPanel',()=>({ManualDemoPanel:()=>null}));
vi.mock('@/components/ui/page-header',()=>({PageHeader:()=>null}));
afterEach(()=>vi.unstubAllEnvs());
describe('paper-trading example data notice',()=>{
 it('labels local fixtures when Mongo is absent',async()=>{
  vi.stubEnv('NODE_ENV','development');vi.stubEnv('MONGODB_URI','');
  render(await PaperTradingPage());
  expect(screen.getByRole('note')).toHaveTextContent('Datos de ejemplo para QA visual');
  expect(screen.getByRole('note')).toHaveTextContent('registrar operaciones fallará');
  expect(mocks.account).not.toHaveBeenCalled();
 });
 it.each([['production',''],['development','mongodb://test.invalid/local']])('does not label fetched account as fixtures (%s)',async(env,uri)=>{
  vi.stubEnv('NODE_ENV',env);vi.stubEnv('MONGODB_URI',uri);
  mocks.account.mockResolvedValue({ok:false,message:'Cuenta no disponible'});
  mocks.history.mockResolvedValue({ok:false,message:'Sin historial'});
  mocks.valuation.mockResolvedValue({ok:false});
  render(await PaperTradingPage());
  expect(screen.queryByRole('note')).not.toBeInTheDocument();
  expect(screen.getByText(/Cuenta no disponible/)).toBeVisible();
 });
});
