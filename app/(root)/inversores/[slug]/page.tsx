import type { Metadata } from "next";
import { notFound } from "next/navigation";

import BackendOffline from "@/components/system/BackendOffline";
import {
  getInvestor,
  getInvestors,
  getInvestorPortfolio,
} from "@/lib/actions/investors.actions";
import { isBackendUnavailableError } from "@/lib/backend-offline";
import { getKnowledgeLetters } from "@/lib/actions/research-tools.actions";
import { Portfolio } from "../_components/Portfolio";
import { InvestorLetters } from "../_components/InvestorLetters";
import { InvestorSelector } from "../_components/InvestorSelector";
import { InvestorViewSelector, VIEWS } from "../_components/InvestorViewSelector";
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

  let choices: Awaited<ReturnType<typeof getInvestors>>;
  let investor: Awaited<ReturnType<typeof getInvestor>>;
  let portfolio: Awaited<ReturnType<typeof getInvestorPortfolio>> | null = null;
  let documents: Awaited<ReturnType<typeof getKnowledgeLetters>> = [];
  let lettersUnavailable = false;
  try {
    [investor, choices] = await Promise.all([getInvestor(slug), getInvestors()]);
    if (!investor) notFound();
    if (view !== "cartas" && view !== "videos") {
      portfolio = await getInvestorPortfolio(slug);
    } else if (view === "cartas") {
      try {
        documents = await getKnowledgeLetters();
      } catch (error) {
        if (!isBackendUnavailableError(error)) throw error;
        lettersUnavailable = true;
      }
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

  const photo = INVESTOR_PHOTOS[investor.slug];

  return (
    <main
      id="content"
      tabIndex={-1}
      className="mx-auto flex w-full min-w-0 max-w-4xl flex-col gap-5 overflow-x-clip py-6"
    >
      <InvestorSelector investors={choices.investors} selected={investor.slug} />

      <header className="flex items-center gap-3">
        <InvestorAvatar name={investor.name} size="lg" slug={investor.slug} />
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold sm:text-2xl text-gray-100">
            {investor.name}
          </h1>
          <p className="text-base text-gray-500">{investor.firm}</p>
          {photo ? (
            <p className="mt-1 text-xs text-gray-500">
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

      <InvestorViewSelector slug={investor.slug} view={view ?? "posiciones"} />
      {view !== "cartas" && view !== "videos" && portfolio ? <>
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
      </> : null}
      {view === "cartas" ? <InvestorLetters
        slug={investor.slug}
        documents={documents}
        unavailable={lettersUnavailable}
        pagina={pagina}
        publicLetters={investor.public_profile?.letters}
      /> : null}
      {view === "videos" ? <InvestorVideos videos={investor.videos} /> : null}

      <InvestorConcepts slug={investor.slug} />
    </main>
  );
}
