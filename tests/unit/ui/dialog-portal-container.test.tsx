import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogPortal, DialogPortalContainerProvider } from '@/components/ui/dialog';

describe('nested portal destination', () => {
    it('keeps nested Radix content inside the supplied native modal ancestor', () => {
        const nativeDialog = document.createElement('dialog');
        document.body.append(nativeDialog);
        nativeDialog.open = true; // jsdom: destination check only, not top layer.
        const result = render(<DialogPortalContainerProvider value={nativeDialog}><Dialog open><DialogContent><DialogTitle>Nested search</DialogTitle><DialogDescription>Destination test</DialogDescription></DialogContent></Dialog></DialogPortalContainerProvider>);
        expect(nativeDialog.querySelector('[data-slot="dialog-content"]')).toBe(screen.getByRole('dialog', { name: 'Nested search' }));
        result.unmount();
        nativeDialog.remove();
    });
    it('preserves explicit portal destination over the inherited one', () => {
        const inherited = document.createElement('div');
        const explicit = document.createElement('div');
        document.body.append(inherited, explicit);
        const result = render(<DialogPortalContainerProvider value={inherited}><Dialog open><DialogPortal container={explicit}><span>Explicit destination</span></DialogPortal></Dialog></DialogPortalContainerProvider>);
        expect(explicit).toContainElement(screen.getByText('Explicit destination'));
        expect(inherited).toBeEmptyDOMElement();
        result.unmount(); inherited.remove(); explicit.remove();
    });
});
