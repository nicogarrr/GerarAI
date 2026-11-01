import Link from "next/link";
import { getLocale, getT } from "@/lib/i18n/server";
import { conceptsForInvestorIn } from "../conceptos/concepts-i18n";

export async function InvestorConcepts({ slug }: { slug: string }) {
  const t = await getT();
  const concepts = conceptsForInvestorIn(slug, await getLocale());
  return (
    <section
      aria-labelledby="investor-concepts-title"
      className="flex flex-col gap-4 border-t border-gray-800 pt-6"
    >
      <div className="flex items-center justify-between gap-3">
        <h2
          id="investor-concepts-title"
          className="text-xl font-semibold text-gray-100"
        >
          {t('investors.concepts.title')}
        </h2>
        <Link
          className="text-sm text-teal-300 hover:underline"
          href="/inversores/conceptos"
        >
          {t('investors.concepts.seeAll')}
        </Link>
      </div>
      {concepts.length === 0 ? (
        <p className="text-sm text-gray-500">
          {t('investors.concepts.noneForInvestor')}
        </p>
      ) : (
        <ul className="grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2">
          {concepts.map((concept) => (
            <li key={concept.slug}>
              <Link
                className="flex h-full flex-col gap-2 rounded-xl border border-gray-800 p-4 hover:border-gray-600"
                href={`/inversores/conceptos/${concept.slug}`}
              >
                <h3 className="text-sm font-medium text-gray-100">
                  {concept.title}
                </h3>
                <p className="text-xs text-gray-500">{concept.summary}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
