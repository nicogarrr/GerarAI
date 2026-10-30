import { Metadata } from 'next';
import Link from 'next/link';
import {
  BookOpen,
  Calculator,
  Database,
  FlaskConical,
  LineChart,
  Scale,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Target,
  TriangleAlert,
  Users,
  Wallet,
} from 'lucide-react';

import { GlossaryTerm } from '@/components/GlossaryTerm';
import { Button } from '@/components/ui/button';
import { getT } from '@/lib/i18n/server';

export const dynamic = 'force-dynamic';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return {
    title: t('landing.metodologia.metaTitle'),
    description: t('landing.metodologia.metaDescription'),
    robots: { index: true, follow: true },
    alternates: { canonical: '/metodologia' },
  };
}

export default async function MetodologiaPage() {
  const t = await getT();

  const sources = [
    {
      icon: Database,
      title: t('landing.metodologia.sources.finnhub.title'),
      text: t('landing.metodologia.sources.finnhub.text'),
      href: '/research',
      cta: t('landing.metodologia.sources.finnhub.cta'),
    },
    {
      icon: LineChart,
      title: t('landing.metodologia.sources.yahoo.title'),
      text: t('landing.metodologia.sources.yahoo.text'),
      href: '/',
      cta: t('landing.metodologia.sources.yahoo.cta'),
    },
    {
      icon: Users,
      title: t('landing.metodologia.sources.sec.title'),
      text: t('landing.metodologia.sources.sec.text'),
      href: '/insider',
      cta: t('landing.metodologia.sources.sec.cta'),
    },
    {
      icon: Database,
      title: t('landing.metodologia.sources.others.title'),
      text: t('landing.metodologia.sources.others.text'),
      href: '/research',
      cta: t('landing.metodologia.sources.others.cta'),
    },
  ];

  const engines = [
    {
      title: t('landing.metodologia.engines.dcf.title'),
      text: (
        <>
          {t('landing.metodologia.engines.dcf.textPre')}{' '}
          <GlossaryTerm k="wacc" icon={false}>
            {t('landing.metodologia.engines.dcf.textWacc')}
          </GlossaryTerm>{' '}
          {t('landing.metodologia.engines.dcf.textMid')}{' '}
          <GlossaryTerm k="reverse_dcf" icon={false}>
            {t('landing.metodologia.engines.dcf.textReverseDcf')}
          </GlossaryTerm>{' '}
          {t('landing.metodologia.engines.dcf.textPost')}
        </>
      ),
    },
    {
      title: t('landing.metodologia.engines.preRevenue.title'),
      text: t('landing.metodologia.engines.preRevenue.text'),
    },
    {
      title: t('landing.metodologia.engines.commodities.title'),
      text: t('landing.metodologia.engines.commodities.text'),
    },
    {
      title: t('landing.metodologia.engines.sotp.title'),
      text: t('landing.metodologia.engines.sotp.text'),
    },
    {
      title: t('landing.metodologia.engines.holding.title'),
      text: t('landing.metodologia.engines.holding.text'),
    },
  ];

  const steps = [
    {
      title: t('landing.metodologia.propicks.step1.title'),
      text: t('landing.metodologia.propicks.step1.text'),
    },
    {
      title: t('landing.metodologia.propicks.step2.title'),
      text: t('landing.metodologia.propicks.step2.text'),
    },
    {
      title: t('landing.metodologia.propicks.step3.title'),
      text: t('landing.metodologia.propicks.step3.text'),
    },
    {
      title: t('landing.metodologia.propicks.step4.title'),
      text: t('landing.metodologia.propicks.step4.text'),
    },
  ];

  const limits = [
    {
      icon: TriangleAlert,
      title: t('landing.metodologia.limits.delay.title'),
      text: t('landing.metodologia.limits.delay.text'),
    },
    {
      icon: ShieldAlert,
      title: t('landing.metodologia.limits.coverage.title'),
      text: t('landing.metodologia.limits.coverage.text'),
    },
    {
      icon: Scale,
      title: t('landing.metodologia.limits.pit.title'),
      text: (
        <>
          {t('landing.metodologia.limits.pit.textPre')}{' '}
          <GlossaryTerm k="look_ahead" icon={false}>
            {t('landing.metodologia.limits.pit.textLookAhead')}
          </GlossaryTerm>{' '}
          {t('landing.metodologia.limits.pit.textPost')}
        </>
      ),
    },
    {
      icon: Target,
      title: t('landing.metodologia.limits.advice.title'),
      text: t('landing.metodologia.limits.advice.text'),
    },
  ];

  const costs = [
    {
      icon: Wallet,
      title: t('landing.metodologia.costs.data.title'),
      text: t('landing.metodologia.costs.data.text'),
    },
    {
      icon: FlaskConical,
      title: t('landing.metodologia.costs.llm.title'),
      text: t('landing.metodologia.costs.llm.text'),
    },
    {
      icon: BookOpen,
      title: t('landing.metodologia.costs.infra.title'),
      text: t('landing.metodologia.costs.infra.text'),
    },
  ];

  // Claves literales: el guard i18n solo ve usos estáticos de t().
  const moatChecks = [
    [t('landing.metodologia.moat.check1'), t('landing.metodologia.moat.check1Threshold')],
    [t('landing.metodologia.moat.check2'), t('landing.metodologia.moat.check2Threshold')],
    [t('landing.metodologia.moat.check3'), t('landing.metodologia.moat.check3Threshold')],
    [t('landing.metodologia.moat.check4'), t('landing.metodologia.moat.check4Threshold')],
    [t('landing.metodologia.moat.check5'), t('landing.metodologia.moat.check5Threshold')],
    [t('landing.metodologia.moat.check6'), t('landing.metodologia.moat.check6Threshold')],
    [t('landing.metodologia.moat.check7'), t('landing.metodologia.moat.check7Threshold')],
    [t('landing.metodologia.moat.check8'), t('landing.metodologia.moat.check8Threshold')],
  ];

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex w-full min-w-0 max-w-7xl flex-col gap-6 overflow-x-clip px-4 py-10 md:px-6 lg:px-8">
      <header className="flex flex-col gap-4 border-b border-gray-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase text-teal-300">{t('landing.metodologia.kicker')}</p>
          <h1 className="mt-1 break-words text-2xl font-bold text-gray-100 sm:text-3xl">{t('landing.metodologia.h1')}</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-400">
            {t('landing.metodologia.intro')}
          </p>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline">
            <Link href="/knowledge">
              <BookOpen className="h-4 w-4" />
              {t('landing.metodologia.actions.library')}
            </Link>
          </Button>
          <Button asChild className="h-11 w-full sm:w-auto" variant="outline">
            <Link href="/search">
              <Search className="h-4 w-4" />
              {t('landing.metodologia.actions.search')}
            </Link>
          </Button>
          <Button asChild className="h-11 w-full sm:w-auto">
            <Link href="/propicks">
              <Sparkles className="h-4 w-4" />
              {t('landing.metodologia.actions.propicks')}
            </Link>
          </Button>
        </div>
      </header>

      {/* La página es pública, pero los módulos que enlaza viven dentro de la
          app: se dice aquí, en vez de dejar que un visitante sin cuenta
          descubra el muro de sesión al pulsarlos. */}
      <p className="rounded-xl border border-gray-700/50 bg-surface-overlay p-4 text-sm leading-6 text-gray-300">
        {t('landing.metodologia.publicNotice.body')}{' '}
        <Link href="/sign-up" className="public-footer-link">
          {t('landing.metodologia.publicNotice.createAccount')}
        </Link>{' '}
        {t('landing.metodologia.publicNotice.or')}{' '}
        <Link href="/sign-in" className="public-footer-link">
          {t('landing.metodologia.publicNotice.signIn')}
        </Link>
        .
      </p>

      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Database className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('landing.metodologia.sourcesTitle')}</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {sources.map((source) => (
            <article
              className="flex min-w-0 flex-col rounded-xl border border-gray-800 bg-surface-1 p-4 break-words sm:p-5"
              key={source.title}
            >
              <div className="flex items-center gap-2">
                <source.icon className="h-5 w-5 shrink-0 text-teal-300" />
                <h3 className="font-semibold text-gray-100">{source.title}</h3>
              </div>
              <p className="mt-2 flex-1 text-sm leading-6 text-gray-400">{source.text}</p>
              <Button asChild className="mt-4 h-11 w-full sm:w-fit" size="sm" variant="outline">
                <Link href={source.href}>{source.cta}</Link>
              </Button>
            </article>
          ))}
        </div>
        <p className="mt-4 rounded-xl border border-amber-900/60 bg-amber-950/20 p-4 text-sm leading-6 text-amber-200">
          <strong>{t('landing.metodologia.fmpNotice.lead')}</strong> {t('landing.metodologia.fmpNotice.body')}
        </p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <h2 className="text-lg font-semibold text-gray-100">{t('landing.metodologia.orbital.title')}</h2>
        <p className="mt-2 text-sm leading-6 text-gray-400">{t('landing.metodologia.orbital.body')}</p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Calculator className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('landing.metodologia.engines.title')}</h2>
        </div>
        <p className="mb-4 text-sm leading-6 text-gray-400">
          {t('landing.metodologia.engines.intro')}
        </p>
        <ol className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {engines.map((engine, index) => (
            <li
              className="flex min-w-0 gap-3 rounded-lg border border-gray-800 bg-black/30 p-4 break-words"
              key={engine.title}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-950 text-sm font-semibold text-teal-300">
                {index + 1}
              </span>
              <div className="min-w-0">
                <h3 className="font-semibold text-gray-100">{engine.title}</h3>
                <p className="mt-1 text-sm leading-6 text-gray-400">{engine.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-xs leading-5 text-gray-500">
          {t('landing.metodologia.engines.footnote')}
        </p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Sparkles className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('landing.metodologia.propicks.title')}</h2>
        </div>
        <ol className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {steps.map((step, index) => (
            <li
              className="flex min-w-0 gap-3 rounded-lg border border-gray-800 bg-black/30 p-4 break-words"
              key={step.title}
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-teal-950 text-sm font-semibold text-teal-300">
                {index + 1}
              </span>
              <div className="min-w-0">
                <h3 className="font-semibold text-gray-100">{step.title}</h3>
                <p className="mt-1 text-sm leading-6 text-gray-400">{step.text}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-sm leading-6 text-gray-400">
          {t('landing.metodologia.propicks.footnote')}
        </p>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Search className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">
            {t('landing.metodologia.funnel.title')}
          </h2>
        </div>
        <div className="space-y-3 text-sm leading-6 text-gray-400">
          <p>
            {t('landing.metodologia.funnel.introPre')}{' '}
            <strong className="text-gray-200">{t('landing.metodologia.funnel.introStrong')}</strong>{' '}
            {t('landing.metodologia.funnel.introPost')}
          </p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <strong className="text-gray-200">{t('landing.metodologia.funnel.coverageStrong')}</strong>{' '}
              {t('landing.metodologia.funnel.coverageRest')}
            </li>
            <li>
              <strong className="text-gray-200">{t('landing.metodologia.funnel.consistencyStrong')}</strong>{' '}
              {t('landing.metodologia.funnel.consistencyRest')}
            </li>
            <li>
              <strong className="text-gray-200">{t('landing.metodologia.funnel.debtStrong')}</strong>{' '}
              {t('landing.metodologia.funnel.debtRest')}
            </li>
            <li>
              <strong className="text-gray-200">{t('landing.metodologia.funnel.qualityStrong')}</strong>{' '}
              {t('landing.metodologia.funnel.qualityRest')}
            </li>
            <li>
              <strong className="text-gray-200">{t('landing.metodologia.funnel.rankingStrong')}</strong>{' '}
              {t('landing.metodologia.funnel.rankingRest')}
            </li>
          </ul>
          <p>
            <strong className="text-gray-200">{t('landing.metodologia.funnel.v1Strong')}</strong>{' '}
            {t('landing.metodologia.funnel.v1Rest')}
          </p>
        </div>
      </section>

      <section className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <ShieldCheck className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('landing.metodologia.moat.title')}</h2>
        </div>
        <p className="mb-4 text-sm leading-6 text-gray-400">
          {t('landing.metodologia.moat.intro')}
        </p>
        <ul className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {moatChecks.map(([check, threshold]) => (
            <li
              className="flex min-w-0 items-center justify-between gap-3 rounded-lg border border-gray-800 bg-black/30 p-4 break-words"
              key={check}
            >
              <span className="text-sm text-gray-200">{check}</span>
              <span className="shrink-0 text-sm font-semibold text-teal-300">{threshold}</span>
            </li>
          ))}
        </ul>
        <p className="mt-4 rounded-xl border border-teal-900/60 bg-teal-950/20 p-4 text-sm leading-6 text-teal-100">
          {t('landing.metodologia.moat.noteOwner')}
        </p>
        <p className="mt-4 rounded-xl border border-gray-800 bg-black/30 p-4 text-sm leading-6 text-gray-400">
          {t('landing.metodologia.moat.noteEsef')}
        </p>
      </section>

      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-amber-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('landing.metodologia.limits.title')}</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-2">
          {limits.map((limit) => (
            <article
              className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 break-words sm:p-5"
              key={limit.title}
            >
              <div className="flex items-center gap-2">
                <limit.icon className="h-5 w-5 shrink-0 text-amber-300" />
                <h3 className="font-semibold text-gray-100">{limit.title}</h3>
              </div>
              <p className="mt-2 text-sm leading-6 text-gray-400">{limit.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <Wallet className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">{t('landing.metodologia.costs.title')}</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:gap-4 md:grid-cols-3">
          {costs.map((cost) => (
            <article
              className="min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 break-words sm:p-5"
              key={cost.title}
            >
              <div className="flex items-center gap-2">
                <cost.icon className="h-5 w-5 shrink-0 text-teal-300" />
                <h3 className="font-semibold text-gray-100">{cost.title}</h3>
              </div>
              <p className="mt-2 text-sm leading-6 text-gray-400">{cost.text}</p>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
