import React from 'react';
import {act, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, describe, expect, it, vi} from 'vitest';
import SectionNav from '@/components/layout/SectionNav';

vi.mock('next/navigation',()=>({usePathname:()=>'/research'}));
vi.mock('next/link',()=>({default:({children,scroll:_scroll,...props}:React.PropsWithChildren<Record<string,unknown>>)=><a {...props}>{children}</a>}));
vi.mock('@/lib/i18n/client',()=>({useT:()=> (key:string)=>key}));
vi.mock('@/components/ui/overflow-scroll-region',()=>({OverflowScrollRegion:({children}:React.PropsWithChildren)=><div>{children}</div>}));

afterEach(()=>{localStorage.clear();vi.unstubAllGlobals();});
describe('SectionNav hydration',()=>{
 it('cannot lose an early click before the saved preference is loaded',()=>{
  const queued:VoidFunction[]=[];
  vi.stubGlobal('queueMicrotask',(fn:VoidFunction)=>queued.push(fn));
  render(<SectionNav/>);
  const toggle=screen.getByRole('button');
  expect(toggle).toBeDisabled();
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded','false');
  act(()=>{queued.splice(0).forEach(fn=>fn());});
  expect(toggle).toBeEnabled();
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded','true');
  expect(localStorage.getItem('subnav-seccion')).toBe('abierto');
 });
 it('loads the saved open preference before enabling the button',()=>{
  const queued:VoidFunction[]=[];
  localStorage.setItem('subnav-seccion','abierto');
  vi.stubGlobal('queueMicrotask',(fn:VoidFunction)=>queued.push(fn));
  render(<SectionNav/>);
  const toggle=screen.getByRole('button');
  expect(toggle).toBeDisabled();
  act(()=>{queued.splice(0).forEach(fn=>fn());});
  expect(toggle).toBeEnabled();
  expect(toggle).toHaveAttribute('aria-expanded','true');
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded','false');
  expect(localStorage.getItem('subnav-seccion')).toBe('cerrado');
 });
});
