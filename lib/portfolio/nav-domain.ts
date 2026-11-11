/**
 * Dominio del eje Y del gráfico de NAV de cartera.
 *
 * Antes era `['dataMin - 50', 'dataMax + 50']`: un margen fijo de 50 € sin
 * relación con la escala de la serie. Con un NAV de decenas de miles el
 * margen era invisible y la curva llenaba todo el alto del gráfico, de modo
 * que una variación mínima parecía un desplome; con valores pequeños la
 * curva quedaba plana en el centro. El margen es ahora el 5 % del rango de
 * la serie, con un suelo para series planas (rango 0) que evita un dominio
 * degenerado de ancho cero.
 */
export function navYDomain(values: readonly number[]): [number, number] {
    if (values.length === 0) return [0, 1];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min;
    const pad = range > 0 ? range * 0.05 : Math.max(Math.abs(min) * 0.01, 1);
    return [min - pad, max + pad];
}
