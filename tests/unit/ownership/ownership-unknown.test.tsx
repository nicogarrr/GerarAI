import {renderToStaticMarkup} from 'react-dom/server';
import {writeFileSync} from 'node:fs';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import {mobileHoldings,mobileChanges} from '../../fixtures/ownership-mobile';
const mocks=vi.hoisted(()=>({locale:'es',managers:vi.fn(),holdings:vi.fn(),changes:vi.fn()}));
vi.mock('next/headers',()=>({cookies:async()=>({get:()=>({value:mocks.locale})})}));
vi.mock('@/lib/actions/ownership.actions',()=>({getOwnershipManagers:mocks.managers,getManagerHoldings:mocks.holdings,getManagerChanges:mocks.changes}));
vi.mock('@/app/(root)/ownership/SyncButton',()=>({default:()=>null}));
vi.mock('@/app/(root)/inversores/_components/SyncPortfoliosButton',()=>({SyncPortfoliosButton:()=>null}));
vi.mock('@/app/(root)/ownership/_components/MostBought',()=>({MostBought:()=> <p>Most bought fixture</p>}));
vi.mock('@/app/(root)/ownership/_components/Overlap',()=>({Overlap:()=> <p>Overlap fixture</p>}));
import OwnershipPage from '@/app/(root)/ownership/page';
// Tabla responsiva única (2026-11-14): cada aviso/badge vive una vez por fila
// (antes duplicado: tarjeta móvil + tabla escritorio).
const dataRows=()=>screen.queryAllByRole('row').filter(r=>r.getAttribute('aria-label'));
beforeEach(()=>{mocks.locale='es';mocks.managers.mockReset().mockResolvedValue({managers:[{cik:'1',name:'Fixture Fund'}],limitations:[]});mocks.holdings.mockReset().mockResolvedValue(structuredClone(mobileHoldings));mocks.changes.mockReset().mockResolvedValue(structuredClone(mobileChanges));});

it('muestra comparaciones incompletas sin contarlas como movimientos', async () => {
 const notice = 'Comparación incompleta: faltan acciones válidas; no se infiere una compra ni venta.';
 mocks.changes.mockResolvedValue({...mobileChanges, changes:[{...mobileChanges.changes[0], change:'unknown', notice, shares_previous:null}]});
 const page = await OwnershipPage({searchParams:Promise.resolve({})});
 if(process.env.OWNERSHIP_PREVIEW) writeFileSync('/tmp/ownership-unknown.html', '<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/tmp/ownership-style.css"></head><body style="background:#080808;color:#ddd;padding:16px">'+renderToStaticMarkup(page)+'</body></html>');
 render(page);
 expect(screen.getAllByText('comparación incompleta')).toHaveLength(1);
 expect(screen.getAllByText(notice)).toHaveLength(1);
 expect(screen.getByText('0 movimientos')).toBeInTheDocument();
 expect(screen.queryByText(/Sin movimientos entre/)).toBeNull();
 expect(within(dataRows()[1]).getByText('N/D')).toBeInTheDocument();
});
it('conserva movimientos confirmados y no inventa avisos en filas completas', async () => {
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(screen.getByText('1 movimientos')).toBeInTheDocument();
 expect(screen.queryByText('comparación incompleta')).toBeNull();
});

it('traduce el aviso y conserva limitaciones de comparación sin duplicarlas', async () => {
 mocks.locale='en';
 const notice = 'Comparación incompleta: faltan acciones válidas en uno o ambos periodos; no se infiere una compra, venta ni posición sin cambios.';
 const limitation = 'Comparación incompleta en algunas posiciones: consulta el aviso de cada fila.';
 mocks.managers.mockResolvedValue({managers:[{cik:'1',name:'Fixture Fund'}],limitations:[limitation]});
 mocks.changes.mockResolvedValue({...mobileChanges,limitations:[limitation],changes:[{...mobileChanges.changes[0],change:'unknown',notice}]});
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(screen.getAllByText('incomplete comparison')).toHaveLength(1);
 expect(screen.getAllByText(/Incomplete comparison: valid share counts/)).toHaveLength(1);
 expect(screen.getAllByText('Incomplete comparison for some positions: see each row notice.')).toHaveLength(1);
});
it('traduce el aviso nuevo de unidades no comparables (#5479) y sigue traduciendo el anterior', async () => {
 mocks.locale='en';
 const noticeNew = 'Comparación incompleta: faltan cantidades válidas o las unidades no son comparables; no se infiere una compra, venta ni posición sin cambios.';
 const noticeOld = 'Comparación incompleta: faltan acciones válidas en uno o ambos periodos; no se infiere una compra, venta ni posición sin cambios.';
 mocks.changes.mockResolvedValue({...mobileChanges, changes:[
  {...mobileChanges.changes[0], change:'unknown', notice:noticeNew, shares_previous:null},
  {...mobileChanges.changes[0], cusip:'987654321', change:'unknown', notice:noticeOld, shares_previous:null},
 ]});
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(screen.getAllByText('Incomplete comparison: valid quantities are missing or the units are not comparable; no purchase, sale or unchanged position is inferred.')).toHaveLength(1);
 expect(screen.getAllByText('Incomplete comparison: valid share counts are missing in one or both periods; no purchase, sale or unchanged position is inferred.')).toHaveLength(1);
});
it('no oculta avisos nuevos y no clasifica las filas desconocidas como compras', async () => {
 mocks.changes.mockResolvedValue({...mobileChanges,changes:[mobileChanges.changes[0],{...mobileChanges.changes[0],cusip:'987654321',change:'unknown',notice:'Aviso nuevo de la fuente'}]});
 render(await OwnershipPage({searchParams:Promise.resolve({})}));
 expect(screen.getByText('1 movimientos')).toBeInTheDocument();
 expect(screen.getAllByText('Aviso nuevo de la fuente')).toHaveLength(1);
 expect(screen.getAllByText('comparación incompleta')).toHaveLength(1);
});
