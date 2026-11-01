import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getT } from "@/lib/i18n/server";
import { conceptsFor } from "./concepts-i18n";
import { Pagination, paginate } from "../_components/Pagination";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('investors.concepts.metaTitle') };
}

export default async function ConceptsPage({
  searchParams,
}: {
  searchParams: Promise<{ pagina?: string }>;
}) {
  const { pagina } = await searchParams;
  const t = await getT();
  const paged = paginate(conceptsFor(await getLocale()), pagina, 12);
  return (
    <main
      id="content"
      tabIndex={-1}
      className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-8 overflow-x-clip py-6"
    >
      <h1 className="text-3xl font-semibold text-gray-100">{t('investors.concepts.title')}</h1>
      <ul className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
        {paged.items.map((concept) => (
          <li key={concept.slug}>
            <Link
              className="flex h-full flex-col gap-3 rounded-2xl border border-gray-800 bg-surface-1 p-6 hover:border-gray-600"
              href={`/inversores/conceptos/${concept.slug}`}
            >
              <h2 className="text-lg font-medium text-gray-100">
                {concept.title}
              </h2>
              <p className="text-sm text-gray-400">{concept.summary}</p>
              <span className="text-xs text-gray-500">
                {concept.source.title}
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <Pagination
        basePath="/inversores/conceptos"
        page={paged.page}
        total={paged.total}
      />
    </main>
  );
}
