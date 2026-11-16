import React from 'react';
import {render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
vi.mock('next/navigation',()=>({usePathname:()=>'/calendar'}));
vi.mock('@/lib/actions/politicians.actions',()=>({getPoliticians:vi.fn()}));
vi.mock('@/components/research/PoliticianCard',()=>({PoliticianCardView:()=>null}));
import {CompanyNavigation} from '@/components/research/CompanyNavigation';
import {CalendarTabs} from '@/components/calendar/CalendarTabs';
import {PoliticiansListSection} from '@/components/insider/PoliticiansListSection';
it('company tabs expose the existing horizontal scroll cue',()=>{
 render(<CompanyNavigation ticker="ASTS" activeView="overview"/>);
 expect(screen.getByTestId('company-navigation')).toHaveClass('scroll-affordance-x','overflow-x-auto');
 expect(screen.getByTestId('company-navigation')).not.toHaveClass('scrollbar-hide');
});
it('calendar tabs expose the same cue without changing destinations',()=>{
 render(<CalendarTabs/>);expect(screen.getByRole('navigation')).toHaveClass('scroll-affordance-x','overflow-x-auto');
 expect(screen.getByRole('navigation')).not.toHaveClass('scrollbar-hide');
});
it('all three politician filter groups expose the same cue',()=>{
 render(<PoliticiansListSection view={{camara:'all',partido:'all',orden:'trades',q:'',shown:30,data:null,offline:false}}/>);
 const groups=screen.getAllByRole('group');expect(groups).toHaveLength(3);
 for(const group of groups){expect(group).toHaveClass('scroll-affordance-x','overflow-x-auto');expect(group).not.toHaveClass('scrollbar-hide');}
});
