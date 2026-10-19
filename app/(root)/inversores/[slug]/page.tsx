import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import BackendOffline from "@/components/system/BackendOffline";
import {
  getInvestor,
  getInvestorPortfolio,
} from "@/lib/actions/investors.actions";
import { isBackendUnavailableError } from "@/lib/backend-offline";
import { getKnowledgeLetters } from "@/lib/actions/research-tools.actions";
import { Portfolio } from "../_components/Portfolio";
import { InvestorLetters } from "../_components/InvestorLetters";
import { InvestorConcepts } from "../_components/InvestorConcepts";

import { InvestorVideos } from "../_components/InvestorVideos";
import { InvestorAvatar } from "../_components/Avatar";
import { INVESTOR_PHOTOS } from "../_components/photos";
import { PublicProfileSection } from "../_components/PublicProfile";
import { SyncPortfoliosButton } from "../_components/SyncPortfoliosButton";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type PageProps = {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ vista?: string; pagina?: string }>;
};

const VIEWS = [
  { id: "posiciones", label: "Posiciones" },
  { id: "distribucion", label: "Distribución" },
  { id: "cambios", label: "Cambios" },
] as const;

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  try {
    const investor = await getInvestor(slug);
    return { title: investor ? `Inversores · ${investor.name}` : 'Inversor no encontrado' };
  } catch {
    return { title: 'Inversores' };
  }
}

export default async function InvestorPage({
  params,
  searchParams,
}: PageProps) {
  const { slug } = await params;
  const { vista, pagina } = await searchParams;
  const view = VIEWS.some((item) => item.id === vista) ? vista : "posiciones";

  let investor: Awaited<ReturnType<typeof getInvestor>>;
  let portfolio: Awaited<ReturnType<typeof getInvestorPortfolio>>;
  let documents: Awaited<ReturnType<typeof getKnowledgeLetters>> = [];
  let lettersUnavailable = false;
  try {
    investor = await getInvestor(slug);
    if (!investor) notFound();
    portfolio = await getInvestorPortfolio(slug);
    try {
      documents = await getKnowledgeLetters();
    } catch (error) {
      if (!isBackendUnavailableError(error)) throw error;
      lettersUnavailable = true;
    }
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return (
        <BackendOffline
          feature="Inversores"
          retryHref={`/inversores/${slug}`}
        />
      );
    }
    throw error;
  }
  if (!investor) notFound();

  const photo = INVESTOR_PHOTOS[investor.slug];

  return (
    <main
      id="content"
      tabIndex={-1}
      className="mx-auto flex w-full min-w-0 max-w-4xl flex-col gap-10 overflow-x-clip py-6"
    >
      <Link
        className="text-sm text-gray-500 hover:text-gray-300"
        href="/inversores"
      >
        Inversores
      </Link>

      <header className="flex items-center gap-5">
        <InvestorAvatar name={investor.name} size="lg" slug={investor.slug} />
        <div className="min-w-0">
          <h1 className="truncate text-3xl font-semibold text-gray-100">
            {investor.name}
          </h1>
          <p className="text-base text-gray-500">{investor.firm}</p>
          {photo ? (
            <p className="mt-1 text-xs text-gray-600">
              Foto: {photo.author},{" "}
              <a
                className="hover:underline"
                href={photo.licenseUrl}
                rel="noreferrer"
                target="_blank"
              >
                {photo.license}
              </a>
              , vía{" "}
              <a
                className="hover:underline"
                href={photo.source}
                rel="noreferrer"
                target="_blank"
              >
                Wikimedia Commons
              </a>
            </p>
          ) : null}
        </div>
      </header>

      <nav
        aria-label="Vistas de la cartera"
        className="flex gap-6 border-b border-gray-800"
      >
        {VIEWS.map((item) => (
          <Link
            aria-current={item.id === view ? "page" : undefined}
            className={`-mb-px border-b-2 pb-3 text-sm ${item.id === view ? "border-teal-300 text-gray-100" : "border-transparent text-gray-500 hover:text-gray-300"}`}
            href={`/inversores/${investor.slug}?vista=${item.id}`}
            key={item.id}
            scroll={false}
          >
            {item.label}
          </Link>
        ))}
      </nav>
      {investor.has_13f && portfolio.positions.length === 0 ? (
        <div className="flex flex-col items-center gap-4 rounded-2xl border border-gray-800 bg-surface-1 p-8 text-center">
          <p className="text-gray-300">Aún no hay carteras descargadas en esta cuenta.</p>
          <SyncPortfoliosButton />
        </div>
      ) : (
        <Portfolio
          portfolio={portfolio}
          view={view ?? "posiciones"}
          pagina={pagina}
        />
      )}
      {!investor.has_13f && investor.public_profile ? (
        <PublicProfileSection profile={investor.public_profile} />
      ) : null}
      <InvestorLetters
        slug={investor.slug}
        documents={documents}
        unavailable={lettersUnavailable}
      />
      <InvestorConcepts slug={investor.slug} />
      <InvestorVideos videos={investor.videos} />
    </main>
  );
}
