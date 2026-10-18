import type { Metadata } from "next";
import Link from "next/link";
import BackendOffline from "@/components/system/BackendOffline";
import { getInvestor, getInvestors } from "@/lib/actions/investors.actions";
import { isBackendUnavailableError } from "@/lib/backend-offline";
import { InvestorVideos } from "../_components/InvestorVideos";
import { InvestorAvatar } from "../_components/Avatar";
import { Pagination, paginate } from "../_components/Pagination";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Vídeos de inversores" };

export default async function VideosPage({
  searchParams,
}: {
  searchParams: Promise<{ inversor?: string; pagina?: string }>;
}) {
  const { inversor, pagina } = await searchParams;
  let data: Awaited<ReturnType<typeof getInvestors>>;
  let detail: Awaited<ReturnType<typeof getInvestor>> = null;
  try {
    data = await getInvestors();
    // Unknown slugs never select a different investor's videos silently.
    if (inversor && data.investors.some((item) => item.slug === inversor))
      detail = await getInvestor(inversor);
  } catch (error) {
    if (isBackendUnavailableError(error))
      return (
        <BackendOffline
          feature="Vídeos de inversores"
          retryHref="/inversores/videos"
        />
      );
    throw error;
  }
  const paged = paginate(data.investors, pagina, 12);
  return (
    <main
      id="content"
      tabIndex={-1}
      className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-8 overflow-x-clip py-6"
    >
      <header className="flex flex-wrap justify-between gap-3">
        <h1 className="text-3xl font-semibold text-gray-100">Vídeos</h1>
        <Link
          className="inline-flex min-h-11 items-center text-sm text-lime-300 hover:underline"
          href="/inversores/canales"
        >
          Canales de inversión
        </Link>
      </header>
      <ul className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {paged.items.map((item) => (
          <li key={item.slug}>
            <Link
              aria-current={detail?.slug === item.slug ? "page" : undefined}
              className={`flex items-center gap-3 rounded-xl border p-4 ${detail?.slug === item.slug ? "border-lime-300/60" : "border-gray-800 hover:border-gray-600"}`}
              href={`/inversores/videos?inversor=${item.slug}${paged.page > 1 ? `&pagina=${paged.page}` : ""}`}
            >
              <InvestorAvatar slug={item.slug} name={item.name} />
              <span className="text-sm text-gray-200">{item.name}</span>
            </Link>
          </li>
        ))}
      </ul>
      <Pagination
        basePath="/inversores/videos"
        page={paged.page}
        total={paged.total}
        params={inversor ? { inversor } : {}}
      />
      {detail ? (
        <section className="flex flex-col gap-3">
          <Link
            className="text-lg font-medium text-gray-100 hover:text-lime-300"
            href={`/inversores/${detail.slug}`}
          >
            {detail.name}
          </Link>
          <InvestorVideos videos={detail.videos} />
        </section>
      ) : (
        <div className="rounded-xl border border-gray-800 p-5 text-sm text-gray-400">
          <p>{inversor ? "Inversor no encontrado." : "Selecciona un inversor."}</p>
          {inversor ? <Link href="/inversores/videos" className="mt-2 inline-flex min-h-11 items-center text-teal-300">Volver a la lista de inversores</Link> : null}
        </div>
      )}
    </main>
  );
}
