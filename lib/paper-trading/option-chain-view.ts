/**
 * Vista de la cadena de opciones REAL diferida (CBOE) para el selector
 * guiado del ticket demo. Tipos de transporte UI <-> acción, sin dominio
 * nuevo: la identidad del contrato la define lib/paper-trading/types.ts y
 * la prima tal como la publica CBOE vive en lib/market/cboe-options.ts.
 * Módulo de solo tipos: importable desde cliente y servidor.
 */

/** Última operación real de un contrato (prima por acción, hora NY naive). */
export type DemoOptionChainTrade = { price: number; time: string };

export type DemoOptionChainStrike = {
    strike: number;
    /**
     * Presencia POR TIPO (veracidad): lado AUSENTE = contrato no listado en
     * la fuente; null = listado pero sin operación registrada; objeto =
     * última operación. Un strike con solo call NO puede ofrecerse como put.
     */
    call?: DemoOptionChainTrade | null;
    put?: DemoOptionChainTrade | null;
};

export type DemoOptionChainExpiry = { expiry: string; strikes: DemoOptionChainStrike[] };

export type DemoOptionChainOk = {
    ok: true;
    underlying: string;
    /** Epoch ms en que la fuente entregó la cadena (también si vino de caché). */
    fetchedAt: number;
    expiries: DemoOptionChainExpiry[];
};

export type DemoOptionChainFailure =
    | 'invalidSymbol'
    | 'notCovered'
    | 'sourceUnavailable'
    | 'saturated'
    | 'noAuth';

export type DemoOptionChainResult = DemoOptionChainOk | { ok: false; reason: DemoOptionChainFailure };
