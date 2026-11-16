import {render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
const auth=vi.hoisted(()=>vi.fn());
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>({value:'es'})})}));
vi.mock('next/navigation',()=>({notFound:()=>{throw new Error('NOT_FOUND');}}));
vi.mock('@/lib/auth/require-user',()=>({requireAuthenticatedUser:auth}));
vi.mock('@/lib/auth/sign-in-redirect',()=>({redirectToSignIn:()=>{throw new Error('SIGN_IN');}}));
vi.mock('@/components/PersonalizedOverview',()=>({default:()=>null}));
vi.mock('@/components/calendar/EarningsDayStrip',()=>({default:()=>null}));
vi.mock('@/app/(root)/inicio/PortfolioNews',()=>({PortfolioNews:()=>null}));
vi.mock('@/app/(root)/inversores/conceptos/OptionPayoff',()=>({OptionPayoff:()=> <p>Payoff chart</p>}));
import Home,{generateMetadata as homeMetadata} from '@/app/(root)/inicio/page';
import Concepts,{generateMetadata as conceptsMetadata} from '@/app/(root)/inversores/conceptos/page';
import Concept,{generateMetadata as conceptMetadata} from '@/app/(root)/inversores/conceptos/[slug]/page';
it('Inicio requiere sesión antes de devolver dashboard y metadata no duplica marca',async()=>{auth.mockResolvedValueOnce({id:'u'});expect(await Home()).toBeTruthy();auth.mockRejectedValueOnce(new Error('expired'));await expect(Home()).rejects.toThrow('SIGN_IN');expect((await homeMetadata()).title).toHaveProperty('absolute');});
it('metadata de concepto desconocido no inventa ficha y ruta devuelve not found',async()=>{expect(await conceptMetadata({params:Promise.resolve({slug:'unknown'})})).toHaveProperty('title');await expect(Concept({params:Promise.resolve({slug:'unknown'})})).rejects.toThrow('NOT_FOUND');expect(await conceptsMetadata()).toBeTruthy();expect(await Concepts({searchParams:Promise.resolve({})})).toBeTruthy();});
it('concepto opciones incluye payoff y conserva fuente de referencia',async()=>{render(await Concept({params:Promise.resolve({slug:'opciones'})}));expect(screen.getByText('Payoff chart')).toBeInTheDocument();expect(screen.getByRole('heading',{level:1})).toHaveTextContent(/opciones/i);expect(document.querySelector('a[target="_blank"]')).toHaveAttribute('href');});

it('concepto con autor conocido y slug nuevo conserva rutas y nombre sin inventar alias',async()=>{const corpus=await import('@/app/(root)/inversores/conceptos/concepts-i18n');const seed=corpus.conceptsFor('es')[0];const spy=vi.spyOn(corpus,'conceptsFor').mockReturnValue([{...seed,slug:'test-editorial',investors:['buffett','nuevo-autor']}]);try{render(await Concept({params:Promise.resolve({slug:'test-editorial'})}));expect(screen.getByRole('link',{name:/Warren Buffett/})).toHaveAttribute('href','/inversores/buffett');expect(screen.getByRole('link',{name:/nuevo-autor/})).toHaveAttribute('href','/inversores/nuevo-autor');expect(screen.queryByText('Payoff chart')).toBeNull();}finally{spy.mockRestore();}});
