import type { DataRecord } from '@/components/data/RecordViews';

/** Informe regenerado en cliente, etiquetado con su ejercicio. */
export type ReportOverride = {
    year: number;
    report: DataRecord | null;
};

/**
 * Informe que debe mostrar /taxes para el ejercicio pedido.
 *
 * La fuente de verdad es el informe que el servidor trajo para ESE año
 * (`initialReport`): año e informe llegan juntos en el mismo render, asi que
 * nunca se puede mostrar el informe de 2026 bajo el titulo «Informe fiscal
 * 2025» (F260). El override local solo existe tras pulsar «Regenerar», y solo
 * aplica si su ejercicio etiquetado coincide con el de la vista; al cambiar de
 * año se descarta solo, sin efectos ni estados espejo que puedan quedarse
 * viejos un render.
 */
export function reportForYear(
    override: ReportOverride | null,
    initialReport: DataRecord | null,
    year: number,
): DataRecord | null {
    return override && override.year === year ? override.report : initialReport;
}
