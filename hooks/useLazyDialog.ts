import { useState } from 'react';

/**
 * Estado compartido de los gatillos de diálogo diferido (AddTransaction,
 * WatchlistAdd, WorkProduct): el contenido pesado se carga al abrir y, una
 * vez abierto por primera vez, el diálogo se queda montado (oculto por Radix
 * al cerrar) para conservar lo escrito si se cierra sin enviar.
 * `openDialog` es la apertura programada (enlace directo por query): marca
 * la primera apertura igual que el gesto del usuario.
 */
export function useLazyDialog(): {
    open: boolean;
    openedOnce: boolean;
    onOpenChange: (next: boolean) => void;
    openDialog: () => void;
    setOpen: (next: boolean) => void;
} {
    const [open, setOpen] = useState(false);
    const [openedOnce, setOpenedOnce] = useState(false);
    const onOpenChange = (next: boolean) => {
        setOpen(next);
        if (next) setOpenedOnce(true);
    };
    const openDialog = () => {
        setOpenedOnce(true);
        setOpen(true);
    };
    return { open, openedOnce, onOpenChange, openDialog, setOpen };
}
