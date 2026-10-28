'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import { FileOutput } from 'lucide-react';
import { Dialog, DialogTrigger } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

// El diálogo de generación (buscador de ticker, selects, la acción y el
// visor markdown del resultado) solo hace falta al abrirlo: importado
// estático viajaba en el bundle inicial de /research. El gatillo queda eager
// con precarga del chunk en pointerdown/focus; el contenido llega al abrir.
const loadWorkProductDialog = () => import('./WorkProductDialog');
const WorkProductDialog = dynamic(loadWorkProductDialog, { loading: () => null });

export default function WorkProductButton() {
    const [open, setOpen] = useState(false);
    // Una vez abierto por primera vez, el diálogo se queda montado (oculto
    // por Radix al cerrar) para conservar lo elegido si se cierra sin generar.
    const [openedOnce, setOpenedOnce] = useState(false);

    return (
        <Dialog
            open={open}
            onOpenChange={(next) => {
                setOpen(next);
                if (next) setOpenedOnce(true);
            }}
        >
            <DialogTrigger asChild>
                <Button
                    variant="outline"
                    onPointerDown={() => void loadWorkProductDialog()}
                    onFocus={() => void loadWorkProductDialog()}
                    className="gap-2 border-gray-700 text-gray-300 hover:text-teal-400"
                >
                    <FileOutput aria-hidden="true" className="h-4 w-4" />
                    Generar entregable
                </Button>
            </DialogTrigger>
            {openedOnce && <WorkProductDialog />}
        </Dialog>
    );
}
