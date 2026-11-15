import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Popover, PopoverContent, PopoverTrigger, PopoverAnchor } from '@/components/ui/popover';
import { DialogPortalContainerProvider } from '@/hooks/useDialogPortalContainer';

describe('popover inside native modal', () => {
    it('keeps the body destination when no native modal provider exists', () => {
        const view = render(<Popover open><PopoverTrigger>Global trigger</PopoverTrigger><PopoverContent>Global result</PopoverContent></Popover>);
        expect(document.body).toContainElement(screen.getByText('Global result'));
        expect(view.container).not.toContainElement(screen.getByText('Global result'));
        expect(screen.getByText('Global result').closest('dialog')).toBeNull();
    });
    it('inherits the native modal portal destination without changing other consumers', () => {
        const dialog = document.createElement('dialog');
        dialog.open = true; // jsdom destination only, no top-layer claim.
        document.body.append(dialog);
        const result = render(<DialogPortalContainerProvider value={dialog}><Popover open><PopoverAnchor><PopoverTrigger>Choose ticker</PopoverTrigger></PopoverAnchor><PopoverContent>Apple fixture result</PopoverContent></Popover></DialogPortalContainerProvider>);
        expect(dialog).toContainElement(screen.getByText('Apple fixture result'));
        result.unmount(); dialog.remove();
    });
});
