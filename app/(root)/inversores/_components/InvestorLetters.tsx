import Link from "next/link";
import { type LetterDoc } from "../cartas/letters";
import { Pagination, paginate } from "./Pagination";
import { investorLetters } from "../cartas/investor-letters";

export function InvestorLetters({
  slug,
  documents,
  unavailable,
  pagina,
  publicLetters = [],
}: {
  slug: string;
  documents: LetterDoc[];
  unavailable?: boolean;
  pagina?: string;
  publicLetters?: { title: string; date: string; url: string }[];
}) {
  const letters = investorLetters(slug, documents);
  const paged = paginate(letters, pagina, 12);
  return (
    <>
    <section
      aria-labelledby="investor-letters-title"
      className="flex flex-col gap-4 border-t border-gray-800 pt-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2
          id="investor-letters-title"
          className="text-xl font-semibold text-gray-100"
        >
          Cartas
        </h2>
      </div>
      {unavailable ? (
        <p role="status" className="text-sm text-amber-300">
          Biblioteca no disponible
        </p>
      ) : letters.length === 0 ? (
        <p className="text-sm text-gray-500">
          N/D · Sin cartas indexadas de este inversor
        </p>
      ) : (
        <ul className="divide-y divide-gray-800">
          {paged.items.map((letter) => (
            <li
              className="flex flex-wrap justify-between gap-2 py-3"
              key={letter.id}
            >
              <Link
                className="text-sm text-gray-200 hover:text-teal-300"
                href={`/inversores/cartas/${letter.id}?inversor=${encodeURIComponent(slug)}`}
              >
                {letter.title}
              </Link>
              <span className="text-xs text-gray-500">
                {letter.publication_date ?? "N/D"}
                {letter.source_url ? <a className="ml-3 text-teal-300" href={letter.source_url} target="_blank" rel="noreferrer">Fuente original</a> : <span> · Fuente N/D</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Pagination basePath={`/inversores/${slug}`} page={paged.page} total={paged.total} params={{ vista: "cartas" }} />
    </section>
    {publicLetters.length > 0 ? <section aria-labelledby="investor-public-sources-title" className="flex flex-col gap-3 border-t border-gray-800 pt-6">
      <h2 id="investor-public-sources-title" className="text-xl font-semibold text-gray-100">Fuentes sobre el inversor</h2>
      <ul className="divide-y divide-gray-800">
        {publicLetters.map((source) => <li key={source.url} className="flex flex-wrap justify-between gap-2 py-3 text-sm">
          <a className="text-teal-300" href={source.url} target="_blank" rel="noreferrer">{source.title} · Fuente original</a>
          <span className="text-xs text-gray-500">{source.date || "N/D"}</span>
        </li>)}
      </ul>
    </section> : null}
    </>
  );
}
