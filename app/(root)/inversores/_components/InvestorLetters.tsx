import Link from "next/link";
import { authorKey, type LetterDoc } from "../cartas/letters";
import { investorLetters } from "../cartas/investor-letters";

export function InvestorLetters({
  slug,
  documents,
  unavailable,
}: {
  slug: string;
  documents: LetterDoc[];
  unavailable?: boolean;
}) {
  const letters = investorLetters(slug, documents);
  return (
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
        <Link
          className="text-sm text-lime-300 hover:underline"
          href={
            letters[0]?.author
              ? `/inversores/cartas?autor=${encodeURIComponent(authorKey(letters[0].author))}`
              : "/inversores/cartas"
          }
        >
          Ver todas
        </Link>
      </div>
      {unavailable ? (
        <p role="status" className="text-sm text-amber-300">
          Biblioteca no disponible
        </p>
      ) : letters.length === 0 ? (
        <p className="text-sm text-gray-500">
          Sin cartas indexadas de este autor
        </p>
      ) : (
        <ul className="divide-y divide-gray-800">
          {letters.slice(0, 4).map((letter) => (
            <li
              className="flex flex-wrap justify-between gap-2 py-3"
              key={letter.id}
            >
              <Link
                className="text-sm text-gray-200 hover:text-lime-300"
                href={`/inversores/cartas/${letter.id}`}
              >
                {letter.title}
              </Link>
              <span className="text-xs text-gray-500">
                {letter.publication_date ?? "Fecha no registrada"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
