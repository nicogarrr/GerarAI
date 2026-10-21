/**
 * Tipos del material oficial (SEC) de un evento de resultados. La resolucion vive en el backend
 * (`GET /api/calendar/followed/materials`, SECClient con la identidad ya configurada); aqui solo
 * el contrato y la ventana de historia que muestra el calendario.
 *
 * `no_disponible` = fallo de red/SEC (NO es ausencia). `sin_cobertura_sec` y `periodo_no_coincide`
 * no pintan nada; `sin_filing` solo se informa tras una lectura correcta de un emisor domestico.
 */

export type MaterialKind = 'nota_prensa' | 'presentacion' | 'documento';

export type MaterialDocument = { kind: MaterialKind; label: string; exhibit: string; url: string };

export type EventMaterials = {
    status: 'ok' | 'sin_filing' | 'no_disponible' | 'sin_cobertura_sec' | 'periodo_no_coincide';
    filed_at: string | null;
    filing_url: string | null;
    documents: MaterialDocument[];
};

/** Dias hacia atras que el calendario sigue mostrando (y enlazando) resultados ya publicados. */
export const HISTORY_DAYS = 7;
