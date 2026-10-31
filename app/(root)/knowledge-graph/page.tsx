import { TickerSearchInput } from '@/components/search/TickerSearchInput';
import type { Metadata } from 'next';
import Link from 'next/link';
import { GitBranch, RefreshCcw } from 'lucide-react';

import KnowledgeGraphCanvas from '@/components/knowledge-graph/KnowledgeGraphCanvas';
import BackendOffline from '@/components/system/BackendOffline';
import { MutationForm } from '@/components/forms/MutationForm';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PageHeader } from '@/components/ui/page-header';
import { Stat } from '@/components/ui/stat';
import { t } from '@/lib/i18n/t';
import { formatConfidence } from '@/lib/format';
import { graphNodeTypeLabel, nodeColor } from '@/lib/knowledge-graph/graph-model';
import { getKnowledgeGraph, getKnowledgeNeighborhood, syncKnowledgeGraph } from '@/lib/actions/research-tools.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export const metadata: Metadata = {
  title: 'Grafo de conocimiento',
  description:
    'Enlaces deterministas entre autores, principios, empresas, KPIs, riesgos, decisiones, lecciones y conceptos, con su procedencia.',
};

export default async function KnowledgeGraphPage({ searchParams }: { searchParams: Promise<{ node_types?: string; ticker?: string; limit?: string; node?: string; depth?: string }> }) {
  const query = await searchParams;
  const selectedNode = Number(query.node) || null;
  // Con query vacío `URLSearchParams.toString()` es '' y la plantilla
  // producía '/knowledge-graph?': el guard `retryHref || '/knowledge-graph'`
  // no lo neutraliza porque '…?' es truthy.
  const queryString = new URLSearchParams(
    Object.entries(query).filter(([, value]) => typeof value === 'string' && value !== ''),
  ).toString();
  const retryHref = queryString ? `/knowledge-graph?${queryString}` : '/knowledge-graph';
  // El motor caido se dice con su motivo (BackendOffline), no con un lienzo
  // vacio: el grafo sin backend no es "un grafo sin nodos", es un grafo que no
  // se ha podido leer. Cualquier otro error (un 404 del backend por un nodo o
  // un ticker que no existe) se propaga al error boundary de la ruta.
  let graph;
  try {
    graph = selectedNode
      ? await getKnowledgeNeighborhood(selectedNode, Number(query.depth) || 2)
      : await getKnowledgeGraph({ nodeTypes: query.node_types, ticker: query.ticker, limit: Number(query.limit) || 120 });
  } catch (error) {
    if (isBackendUnavailableError(error)) return <BackendOffline feature={t('knowledgeGraph.canvas.feature')} retryHref={retryHref} />;
    throw error;
  }
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const typeCounts = Object.entries(graph.nodes.reduce<Record<string, number>>((acc, node) => ({ ...acc, [node.type]: (acc[node.type] ?? 0) + 1 }), {})).sort((a, b) => b[1] - a[1]);
    return <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-[1500px] flex-col gap-6 overflow-x-clip"><PageHeader actions={<MutationForm action={syncKnowledgeGraph} successMessage="Grafo sincronizado"><Button className="h-11 w-full md:w-auto" type="submit"><RefreshCcw aria-hidden="true" className="h-4 w-4" />Sincronizar grafo</Button></MutationForm>} description="Enlaces trazables entre autores, principios, empresas y decisiones." kicker="Research conectado" title="Grafo de conocimiento" />
    {selectedNode ? <div className="flex flex-wrap items-center gap-3 rounded-xl border border-teal-900/50 bg-teal-950/10 p-4"><span className="text-sm text-gray-300">Entorno del nodo #{selectedNode}</span><Button asChild className="ml-auto" size="sm" variant="outline"><Link href="/knowledge-graph">Grafo completo</Link></Button></div> : <form className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4" method="get"><div className="grid grid-cols-1 items-end gap-3 md:grid-cols-[1fr_160px_120px_auto]"><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Tipos de nodo</span><Input className="h-11 w-full" defaultValue={query.node_types} name="node_types" placeholder="Tipos de nodo, separados por comas" /></label><label className="grid min-w-0 content-start gap-1 text-sm text-gray-400"><span>Ticker</span><TickerSearchInput className="h-11 w-full" defaultValue={query.ticker} name="ticker" placeholder="Ticker" /></label><label className="grid content-start gap-1 text-xs text-gray-500">Máximo de nodos<Input className="h-11 w-full" defaultValue={query.limit ?? '120'} max="500" min="1" name="limit" type="number" /></label><Button className="h-11 w-full md:w-auto" type="submit">Filtrar</Button></div></form>}
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-6"><Stat label="Nodos" value={graph.node_count} /><Stat label="Aristas" value={graph.edge_count} />{typeCounts.slice(0, 4).map(([type, count]) => <Stat key={type} label={graphNodeTypeLabel(type)} value={<span style={{ color: nodeColor(type) }}>{count}</span>} />)}{graph.total_node_count != null ? <p className="col-span-full text-xs text-gray-500">Mostrando {graph.node_count} de {graph.total_node_count} nodos con estos filtros. Primero los de más relaciones; solo se muestran relaciones entre los nodos incluidos.</p> : null}</section>
    {/* El dibujo interactivo (pan, zoom, seleccion, busqueda, aislamiento y
        volcado) vive en el cliente; su listado de nodos en texto y el panel de
        detalle se renderizan en el servidor, asi que la pagina no depende del
        JavaScript para ser leida ni para exportar. */}
    <section className="w-full min-w-0 rounded-xl border border-gray-800 bg-surface-0 p-3">
<div className="mb-2 flex flex-wrap gap-2">{typeCounts.map(([type]) => <Badge key={type} variant="outline"><span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: nodeColor(type) }} />{graphNodeTypeLabel(type)}</Badge>)}</div>{graph.nodes.length ? <KnowledgeGraphCanvas graph={graph} /> : <div className="p-10 text-center text-sm text-gray-500"><p className="font-medium text-gray-400">{t('knowledgeGraph.canvas.degradedEmpty')}</p><p className="mt-1">{t('knowledgeGraph.canvas.degradedEmptyHint')}</p></div>}</section>
        <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5"><div className="mb-4 flex items-center gap-2"><GitBranch aria-hidden="true" className="h-5 w-5 text-teal-300" /><h2 className="font-semibold text-gray-100">Relaciones</h2></div>
<div aria-label="Relaciones del grafo" className="hidden overflow-x-auto md:block" role="region" tabIndex={0}><table className="w-full min-w-[640px] text-left text-sm"><caption className="sr-only">Relaciones del grafo de conocimiento: nodo de origen, tipo de relación, nodo de destino y confianza</caption><thead className="text-xs uppercase text-gray-500"><tr><th className="border-b border-gray-800 py-2" scope="col">Desde</th><th className="border-b border-gray-800 py-2" scope="col">Relación</th><th className="border-b border-gray-800 py-2" scope="col">Hasta</th><th className="border-b border-gray-800 px-3 py-2 text-right" scope="col">Confianza</th></tr></thead><tbody>{graph.edges.map((edge) => <tr className="border-b border-gray-900" key={edge.id}><th className="py-3 text-left text-sm font-normal text-gray-300" scope="row">{nodeById.get(edge.from)?.label ?? `Nodo ${edge.from}`}</th><td className="py-3"><Badge variant="outline">{edge.type}</Badge></td><td className="py-3 text-gray-300">{nodeById.get(edge.to)?.label ?? `Nodo ${edge.to}`}</td><td className="px-3 py-3 text-right text-gray-400">{formatConfidence(edge.confidence)}</td></tr>)}{!graph.edges.length ? <tr><td className="py-5 text-gray-500" colSpan={4}>Ninguna relación coincide con el ámbito actual.</td></tr> : null}</tbody></table></div><div className="grid grid-cols-1 gap-3 md:hidden">{!graph.edges.length ? <p className="text-sm text-gray-500">Ninguna relación coincide con el ámbito actual.</p> : null}{graph.edges.slice(0, 30).map((edge) => <article className="min-w-0 rounded-lg border border-gray-800 bg-black/30 p-4 break-words" key={edge.id}><div className="text-sm font-medium text-gray-200">{nodeById.get(edge.from)?.label ?? `Nodo ${edge.from}`}</div><div className="mt-2 flex flex-wrap items-center gap-2"><Badge variant="outline">{edge.type}</Badge><span className="text-xs text-gray-500">→</span><span className="text-sm text-gray-300">{nodeById.get(edge.to)?.label ?? `Nodo ${edge.to}`}</span></div><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500"><span>Confianza {formatConfidence(edge.confidence)}</span></div></article>)}{graph.edges.length > 30 ? <p className="text-xs text-gray-500">Mostrando 30 de {graph.edges.length} relaciones: filtra para acotar el ámbito.</p> : null}</div></section>
  </main>;
}