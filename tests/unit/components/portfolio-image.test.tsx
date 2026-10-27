import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ImportImageButton from '@/components/portfolio/ImportImageButton';
import { imageFileError } from '@/lib/portfolio/image-import';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/lib/actions/portfolio-image.actions', () => ({
    previewPortfolioImage: vi.fn(async () => ({ image_hash: 'a'.repeat(64), rows: [{raw:'ASTS 12 USD',identity:'ASTS',quantity:'12',currency:'USD',warning:'Revisa'}], message:'Revisa las filas' })),
    searchImageInstrument: vi.fn(async () => [{ ticker:'ASTS',name:'AST SpaceMobile',exchange:'NASDAQ',currency:'USD' }]),
    reviewPortfolioImage: vi.fn(async () => ({review_id:1,can_confirm:true,base_currency:'EUR',already_imported:false,rows:[]})),
    confirmPortfolioImage: vi.fn(async () => ({status:'imported',positions_imported:1})),
}));
import { confirmPortfolioImage, previewPortfolioImage, reviewPortfolioImage } from '@/lib/actions/portfolio-image.actions';

describe('captura de cartera', () => {
    it('bloquea tipos y tamaños no soportados', () => {
        expect(imageFileError({type:'image/svg+xml',size:100})).toContain('PNG');
        expect(imageFileError({type:'image/png',size:4*1024*1024})).toContain('2 MB');
        expect(imageFileError({type:'image/png',size:100})).toBeNull();
    });
    it('no guarda al subir ni antes de seleccionar instrumento y revisar', async () => {
        render(<ImportImageButton />);
        fireEvent.click(screen.getByRole('button', {name:'Importar captura'}));
        fireEvent.change(screen.getByLabelText('Elegir captura'), {target:{files:[new File(['png'], 'test.png', {type:'image/png'})]}});
        await waitFor(() => expect(previewPortfolioImage).toHaveBeenCalled());
        await screen.findByText('Leído: ASTS 12 USD');
        expect(screen.getByRole('button', {name:'Consultar precios y revisar'})).toBeDisabled();
        expect(confirmPortfolioImage).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', {name:'Buscar instrumento'}));
        fireEvent.click(await screen.findByRole('button', {name:/ASTS · AST SpaceMobile/}));
        fireEvent.click(screen.getByRole('checkbox'));
        await waitFor(() => expect(screen.getByRole('button', {name:'Consultar precios y revisar'})).toBeEnabled());
        fireEvent.click(screen.getByRole('button', {name:'Consultar precios y revisar'}));
        await waitFor(() => expect(reviewPortfolioImage).toHaveBeenCalledWith('a'.repeat(64), [{ticker:'ASTS',quantity:'12',currency:'USD',confirmed:true}]));
        expect(confirmPortfolioImage).not.toHaveBeenCalled();
        fireEvent.click(await screen.findByRole('button', {name:'Confirmar y guardar posiciones'}));
        await waitFor(() => expect(confirmPortfolioImage).toHaveBeenCalledWith(1));
    });
});
