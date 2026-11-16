import {render} from '@testing-library/react';
import {expect,it} from 'vitest';
import {ResultsSectionSkeleton,ScreenersBodySkeleton} from '@/components/screeners/ScreenersSkeletons';
it('reserves three result cards and excludes loading placeholders from assistive output',()=>{const {container}=render(<ResultsSectionSkeleton/>);const section=container.querySelector('section')!;expect(section).toHaveAttribute('aria-hidden','true');expect(section.children).toHaveLength(4);expect(section.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)});
it('mirrors five workspace blocks with two saved filters and two active metrics',()=>{const {container}=render(<ScreenersBodySkeleton/>);const sections=container.querySelectorAll('section');expect(sections).toHaveLength(5);for(const section of sections)expect(section).toHaveAttribute('aria-hidden','true');expect(sections[1].lastElementChild!.children).toHaveLength(2);expect(sections[4].lastElementChild!.children).toHaveLength(2)});
