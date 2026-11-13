import type {MarketRegime,MarketRegimeResult} from '@/lib/actions/market-regime.actions';
import {render,screen} from '@testing-library/react';import {describe,it,expect,vi} from 'vitest';
const mock=vi.hoisted(()=>({locale:'en',result:{data:null,error:null} as MarketRegimeResult,offline:false}));
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>({value:mock.locale})})}));
vi.mock('@/lib/actions/market-regime.actions',()=>({getMarketRegimeResult:async()=>mock.result}));
vi.mock('@/lib/backend-offline',()=>({isBackendUnavailableError:()=>mock.offline}));
vi.mock('@/components/system/BackendOffline',()=>({default:()=> <p>offline fixture</p>}));
import {MarketRegimeVista,trainingSessionsText,textoRegimen} from '@/components/market/MarketRegime';
import moversEs from '@/lib/i18n/messages/es/movers.json';import moversEn from '@/lib/i18n/messages/en/movers.json';
const date='2026-11-13';
const basic=():MarketRegime=>({coverage:'fixture',status:'disponible',date,generated_at:date+'T14:00:00Z',metrics:{},probabilities:{},note:'Probabilidades filtradas sin etiqueta económica; métricas faltantes indican sin datos.'});
const show=async(data:MarketRegime)=>{mock.result={data,error:null};return render(await MarketRegimeVista());};
describe('Régimen: contratos de presentación ES/EN',()=>{
 it.each(['en','es'])('métricas, métodos y concentración disponibles %s',async locale=>{
  mock.locale=locale;
  await show({...basic(),metrics:{
   treasury_10y_us:{value:4.25,unit:'porcentaje',date},
   treasury_2y_us:{value:4,unit:'desconocida',date},
   yield_curve_10y_2y_us:{value:.25,unit:'puntos porcentuales',date,method:'DGS10 menos DGS2 en la misma fecha'},
   vix_us:{value:15,unit:'índice',date},
   hmm:{status:'disponible',date,trained_through:date,training_sessions:20,method:'historial insuficiente'},
   top_ten_sp500:{status:'disponible',index:'S&P 500',weight_top_ten_pct:35,weight_largest_pct:7,snapshot_as_of:date},
  },probabilities:{state_0:.7,custom:.3},portfolio_beta:{status:'no_disponible',reason:'La beta de tu cartera aún no está disponible.'}});
  expect(screen.getByText(locale==='en'?'4.25%':'4,25 %')).toBeInTheDocument();
  expect(screen.getByText(locale==='en'?'0.25 pp':'0,25 pp')).toBeInTheDocument();
  expect(screen.getByText(locale==='en'?'4.00 desconocida':'4,00 desconocida')).toBeInTheDocument();
  expect(screen.getByText('custom')).toBeInTheDocument();
 });
 it('concentración disponible sin campos opcionales y HMM sin fechas opcionales',async()=>{
  mock.locale='en';await show({...basic(),generated_at:undefined,note:undefined,metrics:{hmm:{status:'disponible'},top_ten_sp500:{status:'disponible',weight_top_ten_pct:35}},probabilities:{state_1:1}});
  expect(screen.getByText('35.0%')).toBeInTheDocument();
 });
 it.each(['obsoleto','sin datos','custom'])('estado %s sin snapshot',async status=>{
  mock.locale='en';await show({...basic(),status,date:undefined});
  expect(screen.queryByText('US 10-year Treasury')).not.toBeInTheDocument();
 });
 it('HMM no disponible, motivo conocido, concentración sin fecha o motivo, beta del bloque metrics',async()=>{
  mock.locale='en';await show({...basic(),generated_at:undefined,metrics:{hmm:{status:'no_disponible',reason:'historial insuficiente'},top_ten_sp500:{status:'sin_datos'},portfolio_beta:{status:'custom',reason:'detalle desconocido'}}});
  expect(screen.getByText('not enough history')).toBeInTheDocument();expect(screen.getByText('detalle desconocido')).toBeInTheDocument();
 });
 it.each(Object.keys(moversEs.regime.concentrationReasons))('reason de concentración %s nunca expone detail',async reason=>{
  mock.locale='en';await show({...basic(),metrics:{top_ten_sp500:{status:'sin_datos',reason,detail:'/private/internal.env',snapshot_as_of:date}}});
  expect(screen.getByText(moversEn.regime.concentrationReasons[reason as keyof typeof moversEn.regime.concentrationReasons])).toBeInTheDocument();
  expect(screen.queryByText('/private/internal.env')).not.toBeInTheDocument();
 });
 it.each([{reason:'unknown'},{detail:'/private/path'}])('concentración fallback seguro %o',async top=>{
  await show({...basic(),metrics:{top_ten_sp500:{status:'sin_datos',...top}}});
  expect(screen.getByText('The S&P 500 factsheet is not available right now.')).toBeInTheDocument();
 });
 it('backend caído',async()=>{mock.offline=true;mock.result={data:null,error:new Error('network')};render(await MarketRegimeVista());expect(screen.getByText('offline fixture')).toBeInTheDocument();mock.offline=false;});
 it('errores desconocidos se propagan y ausencia de datos no se inventa',async()=>{
  mock.result={data:null,error:new Error('unknown')};await expect(MarketRegimeVista()).rejects.toThrow('unknown');
  mock.result={data:null,error:null};mock.locale='en';await expect(MarketRegimeVista()).rejects.toThrow('No market regime response');
 });
 it('singular/plural y claves desconocidas',()=>{
  expect(trainingSessionsText(1,'en')).toBe('1 session');expect(trainingSessionsText(2,'es')).toBe('2 sesiones');
  expect(textoRegimen('__proto__','en')).toBe('__proto__');expect(textoRegimen('constructor','en')).toBe('constructor');
 });
});
