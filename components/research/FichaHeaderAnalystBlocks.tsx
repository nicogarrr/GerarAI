import type { ReactNode } from 'react';

import { showAnalystBlocks, type View } from '@/lib/research/research-views';

type Props = {
    activeView: View;
    /** Objetivos de analistas (ancla #analistas). */
    analystTargets: ReactNode;
    /** Historial de analistas (ancla #historial-analistas). */
    analystHistory: ReactNode;
    /** Señales DCA. */
    dca: ReactNode;
};

/**
 * Puerta de los bloques de analistas de la cabecera de la ficha: solo se
 * montan en Resumen y Finanzas (showAnalystBlocks). En el resto de pestañas
 * empujaban el contenido propio ~1588px abajo en móvil (medido por Piloto
 * en Tesis, 18-nov-2026). Componente de servidor sin estado: la decisión es
 * pura y testeable.
 */
export function FichaHeaderAnalystBlocks({ activeView, analystTargets, analystHistory, dca }: Props) {
    if (!showAnalystBlocks(activeView)) return null;
    return (
        <>
            {analystTargets}
            {analystHistory}
            {dca}
        </>
    );
}
