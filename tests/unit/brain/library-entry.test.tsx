import {fireEvent,render,screen} from '@testing-library/react';
import {expect,it,vi} from 'vitest';
const openBrain=vi.fn();
vi.mock('@/lib/brain/open-brain',()=>({openBrain:(...a:unknown[])=>openBrain(...a)}));
import {LibraryChat} from '@/app/(root)/inversores/_components/LibraryChat';
it('library entry has no separate question form or answer log',()=>{
 render(<LibraryChat scope="letters" authors={['Buffett']}/>);
 expect(screen.queryByRole('textbox')).toBeNull();
 expect(screen.queryByRole('log')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'Preguntar al Cerebro'}));
 expect(openBrain).toHaveBeenCalledWith({knowledge:{scope:'letters',authors:['Buffett']}});
});
