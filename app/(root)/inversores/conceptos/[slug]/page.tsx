import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getLocale, getT } from "@/lib/i18n/server";
import { INVESTOR_NAMES } from "../concepts";
import { conceptsFor } from "../concepts-i18n";
import { OptionPayoff } from "../OptionPayoff";

type Props = { params: Promise<{ slug: string }> };
export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const t = await getT();
  return {
    title:
      conceptsFor(await getLocale()).find((item) => item.slug === slug)?.title ??
      t('investors.concepts.notFound'),
  };
}
export default async function ConceptPage({ params }: Props) {
  const { slug } = await params;
  const t = await getT();
  const concept = conceptsFor(await getLocale()).find((item) => item.slug === slug);
  if (!concept) notFound();
  return (
    <main
      id="content"
      tabIndex={-1}
      className="mx-auto flex w-full min-w-0 max-w-3xl flex-col gap-8 overflow-x-clip py-6"
    >
      <Link
        className="text-sm text-teal-300 hover:underline"
        href="/inversores/conceptos"
      >
        {t('investors.concepts.title')}
      </Link>
      <header className="flex flex-col gap-3">
        <h1 className="text-3xl font-semibold text-gray-100">
          {concept.title}
        </h1>
        <p className="text-base text-gray-400">{concept.summary}</p>
      </header>
      <p className="text-sm leading-7 text-gray-300">{concept.body}</p>
      {slug === "opciones" ? <OptionPayoff /> : null}
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-medium text-gray-100">{t('investors.concepts.application')}</h2>
        <p className="text-sm leading-7 text-gray-300">{concept.application}</p>
      </section>
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-medium text-gray-100">{t('investors.concepts.risk')}</h2>
        <p className="text-sm leading-7 text-gray-300">{concept.risk}</p>
      </section>
      <p className="text-xs text-gray-500">
        {t('investors.concepts.editorial')} ·{" "}
        <a
          className="text-teal-300 hover:underline"
          href={concept.source.url}
          rel="noreferrer"
          target="_blank"
        >
          {concept.source.title}
        </a>
      </p>
      {concept.investors.map((investor) => (
        <Link
          className="text-sm text-teal-300 hover:underline"
          href={`/inversores/${investor}`}
          key={investor}
        >
          {t('investors.concepts.viewInvestor', { name: INVESTOR_NAMES[investor] ?? investor })}
        </Link>
      ))}
    </main>
  );
}
