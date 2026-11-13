'use client';

import Link from 'next/link';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SUPPORT_EMAIL } from '@/lib/config/brand';
import { useT } from '@/lib/i18n/client';




export default function HelpTabs() {
  const t = useT();
  const modules = [
    { href: '/research', title: t('help.modules.item0.title'), text: t('help.modules.item0.text') },
    { href: '/research', title: t('help.modules.item1.title'), text: t('help.modules.item1.text') },
    { href: '/portfolio', title: t('help.modules.item2.title'), text: t('help.modules.item2.text') },
    { href: '/risk', title: t('help.modules.item3.title'), text: t('help.modules.item3.text') },
    { href: '/screeners', title: t('help.modules.item4.title'), text: t('help.modules.item4.text') },
    { href: '/propicks', title: t('help.modules.item5.title'), text: t('help.modules.item5.text') },
    { href: '/alerts', title: t('help.modules.item6.title'), text: t('help.modules.item6.text') },
    { href: '/insider', title: t('help.modules.item7.title'), text: t('help.modules.item7.text') },
    { href: '/knowledge', title: t('help.modules.item8.title'), text: t('help.modules.item8.text') },
    { href: '/watchlist', title: t('help.modules.item9.title'), text: t('help.modules.item9.text') },
    { href: '/metodologia', title: t('help.modules.item10.title'), text: t('help.modules.item10.text') }
  ];
  const faqs = [
    { question: t('help.faqs.item0.question'), answer: t('help.faqs.item0.answer') },
    { question: t('help.faqs.item1.question'), answer: t('help.faqs.item1.answer') },
    { question: t('help.faqs.item2.question'), answer: t('help.faqs.item2.answer') },
    { question: t('help.faqs.item3.question'), answer: t('help.faqs.item3.answer') },
    { question: t('help.faqs.item4.question'), answer: t('help.faqs.item4.answer') }
  ];
  return (
    <main id="content" tabIndex={-1} className="mx-auto w-full max-w-4xl px-4 py-12">
      <div className="text-center mb-12">
        <h1 className="text-4xl font-bold text-gray-100 mb-4">{t('help.title')}</h1>
        <p className="text-xl text-gray-200 mb-4">
          {t('help.subtitle')}
        </p>
        <p className="mt-4 text-sm text-gray-400">
          {t('help.methodologyQuestion')}{' '}
          <Link href="/metodologia" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">
            {t('help.methodologyLink')}
          </Link>
        </p>
        {/* Esta página es pública, pero casi todos los módulos que documenta
            viven dentro de la app. Se avisa aquí para que nadie pulse un enlace
            y se encuentre de golpe con el formulario de acceso. */}
        <p className="mx-auto mt-6 max-w-2xl rounded-lg border border-gray-700/50 bg-gray-800/60 p-4 text-left text-sm text-gray-300">
          {t('help.login.prefix')} <span className="text-gray-100">research</span>,{' '}
          <span className="text-gray-100">{t('help.login.portfolio')}</span>, <span className="text-gray-100">{t('help.login.risk')}</span>,{' '}
          <span className="text-gray-100">ProPicks</span>, <span className="text-gray-100">{t('help.login.alerts')}</span>,{' '}
          <span className="text-gray-100">insiders</span>, <span className="text-gray-100">watchlist</span> {t('help.login.and')}{' '}
          <span className="text-gray-100">{t('help.login.export')}</span>{' '}{t('help.login.description')}{' '}
          <strong className="text-gray-100">{t('help.login.required')}</strong>{t('help.login.public')}
        </p>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="faq" className="w-full">
        <TabsList
          tabIndex={0}
          aria-label={t('help.tabsAria')}
          className="mb-8 flex h-auto w-max min-w-full snap-x gap-1 overflow-x-auto border border-gray-700 bg-gray-800 pb-2 text-gray-400 sm:inline-flex sm:h-9 sm:w-auto sm:overflow-visible sm:pb-[3px]"
        >
          <TabsTrigger
            value="faq"
            className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300"
          >
            FAQs
          </TabsTrigger>
          <TabsTrigger
            value="api"
            className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300"
          >
            {t('help.tabDocs')}
          </TabsTrigger>
          <TabsTrigger
            value="community"
            className="min-h-[44px] min-w-fit flex-none snap-start whitespace-nowrap data-[state=active]:bg-gray-700 data-[state=active]:text-teal-300"
          >
            {t('help.tabContact')}
          </TabsTrigger>
        </TabsList>

        {/* FAQ Tab */}
        <TabsContent value="faq">
          {/* Help Philosophy */}
          <div className="grid md:grid-cols-3 gap-6 mb-12">
            <div className="bg-gray-800 rounded-lg shadow-sm p-6 border hover:shadow-md transition-shadow">
              <h2 className="text-lg font-semibold text-blue-500 mb-2">{t('help.learnTitle')}</h2>
              <p className="text-gray-200 text-sm">
                {t('help.learnText')}
              </p>
            </div>

            <div className="bg-gray-800 rounded-lg shadow-sm p-6 border hover:shadow-md transition-shadow">
              <h2 className="text-lg font-semibold text-green-500 mb-2">{t('help.supportTitle')}</h2>
              <p className="text-gray-200 text-sm">
                {t('help.supportText')}
              </p>
            </div>

            <div className="bg-gray-800 rounded-lg shadow-sm p-6 border hover:shadow-md transition-shadow">
              <h2 className="text-lg font-semibold text-purple-400 mb-2">{t('help.sourcedTitle')}</h2>
              <p className="text-gray-200 text-sm">
                {t('help.sourcedText')}
              </p>
            </div>
          </div>

          {/* Community FAQs */}
          <section className="mb-12">
            <h2 className="text-3xl font-bold text-gray-100 mb-8 text-center">{t('help.faqTitle')}</h2>
            <div className="space-y-4">
              {faqs.map((faq) => (
                <div key={faq.question} className="bg-gray-800 rounded-lg shadow-sm p-6 border">
                  <h3 className="text-lg font-semibold text-gray-100 mb-2">{faq.question}</h3>
                  <p className="text-gray-200">{faq.answer}</p>
                </div>
              ))}
            </div>
          </section>
        </TabsContent>

        {/* Documentation Tab */}
        <TabsContent value="api" className="mt-0">
          <div className="space-y-8">
            <div className="mb-8">
              <h2 className="text-3xl font-bold text-gray-100 mb-4">{t('help.docsTitle')}</h2>
              <p className="text-xl text-gray-200 mb-4">
                {t('help.docsSubtitle')}
              </p>
            </div>

            {/* Primeros pasos */}
            <section className="bg-gray-800 rounded-lg shadow-sm p-6 border">
              <h2 className="text-2xl font-semibold text-gray-100 mb-4">{t('help.firstStepsTitle')}</h2>
              <ol className="space-y-4 text-gray-200">
                <li><strong className="text-teal-400">{t('help.steps.model')}</strong>{' '}
                {t('help.steps.in')}{' '}<Link href="/research" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">Research</Link>{' '}{t('help.steps.modelText')}</li>
                <li><strong className="text-teal-400">{t('help.steps.thesis')}</strong>{' '}{t('help.steps.thesisText')}{' '}
                <Link href="/export" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">/export</Link>{' '}{t('help.steps.exportText')}</li>
                <li><strong className="text-teal-400">{t('help.steps.decision')}</strong>{' '}{t('help.steps.decisionText')}</li>
              </ol>
            </section>

            {/* Guía por módulo */}
            <section className="bg-gray-800 rounded-lg shadow-sm p-6 border">
              <h2 className="text-2xl font-semibold text-gray-100 mb-4">{t('help.moduleGuideTitle')}</h2>
              <div className="grid md:grid-cols-2 gap-4">
                {modules.map((module) => (
                  <div className="bg-gray-900/40 p-4 rounded-lg" key={module.title}>
                    <h3 className="font-semibold text-teal-400 mb-2">
                      <Link href={module.href} className="underline underline-offset-4 hover:text-teal-300">
                        {module.title}
                      </Link>
                    </h3>
                    <p className="text-gray-300 text-sm">{module.text}</p>
                  </div>
                ))}
              </div>
            </section>

            {/* Glosario y metodología */}
            <section className="bg-gray-800 rounded-lg shadow-sm p-6 border">
              <h2 className="text-2xl font-semibold text-gray-100 mb-4">{t('help.glossaryTitle')}</h2>
              <p className="text-gray-200 mb-4">
                {t('help.glossary.text')}{' '}
                <Link href="/metodologia" className="text-teal-400 underline underline-offset-4 hover:text-teal-300">/metodologia</Link>.
              </p>
            </section>
          </div>
        </TabsContent>

        {/* Community Tab */}
        <TabsContent value="community" className="mt-0">
          <section className="bg-gradient-to-r from-blue-900/50 to-purple-900/50 rounded-lg p-8 text-center">
            <h2 className="text-2xl font-bold text-gray-100 mb-4">{t('help.contactTitle')}</h2>
            <p className="text-gray-300 mb-6">
              {SUPPORT_EMAIL
                ? t('help.contactWithEmail')
                : t('help.contactNoEmail')}
            </p>
            {SUPPORT_EMAIL && (
            <div className="flex flex-col sm:flex-row gap-4 justify-center">
                <a
                    href={`mailto:${SUPPORT_EMAIL}`}
                    className="bg-gray-800 text-gray-200 px-6 py-3 rounded-lg hover:bg-gray-700 transition-colors text-center inline-block"
                >
                    {t('help.emailTo')} {SUPPORT_EMAIL}
                </a>
            </div>
            )}
          </section>
        </TabsContent>
      </Tabs>
    </main>
  );
}

