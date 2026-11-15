import { createContext, useContext } from 'react';

// Keep this React-only so the lazy drawer does not eagerly load Radix.
// A nested Radix portal must remain inside its native modal ancestor.
const DialogPortalContainer = createContext<HTMLElement | null>(null);
export const DialogPortalContainerProvider = DialogPortalContainer.Provider;
export const useDialogPortalContainer = () => useContext(DialogPortalContainer);
