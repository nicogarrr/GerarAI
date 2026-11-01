import Link from 'next/link';

// Ayuda en inglés (Ajustes → Idioma). El texto español sigue en HelpTabs.tsx,
// donde lo comprueba scripts/help-copy-honesty-guard.test.ts.
const LINK = 'text-teal-400 underline underline-offset-4 hover:text-teal-300';
const STRONG = 'text-teal-400';
const HI = 'text-gray-100';

export const HELP_EN = {
  title: 'Help center',
  subtitle: 'Documentation, frequently asked questions and support',
  methodologyQuestion: 'Want to see how we analyse and where the data comes from?',
  methodologyLink: 'Methodology and sources',
  tabsAria: 'Help sections',
  tabDocs: 'Documentation',
  tabContact: 'Contact',
  learnTitle: 'Learn',
  learnText: 'The Documentation tab explains what each module does today and how to use it, with links to the methodology and sources.',
  supportTitle: 'Support',
  supportText: 'Support is by email and is handled by the person who maintains the project. Response times are not guaranteed.',
  sourcedTitle: 'Sourced data',
  sourcedText: 'Research figures show their source and date. When verifiable data is missing, the app marks it as not available instead of making it up.',
  faqTitle: 'Frequently asked questions',
  docsTitle: 'Documentation',
  docsSubtitle: 'A practical guide per module: what the app does today and how to use it.',
  firstStepsTitle: 'First steps: model → thesis → decision',
  moduleGuideTitle: 'Module guide',
  glossaryTitle: 'Glossary and methodology',
  contactTitle: 'Contact',
  contactWithEmail: 'Questions or suggestions? Email us.',
  contactNoEmail: 'Questions or suggestions? The contact channel will be published here.',
  emailTo: 'Send an email to',
};

export const MODULES_EN = [
  { href: '/research', title: 'Research', text: 'A page per ticker: canonical financial facts, traceable metrics, thesis, moat, peers, valuation and a chat with sources.' },
  { href: '/research', title: 'Long-term model', text: 'Fundamental model with visible assumptions (growth, FCF margin, WACC), Bear/Base/Bull scenarios with their spreads, owner earnings, TAM/SAM/SOM and reverse DCF. The «Model» tab of the company page.' },
  { href: '/portfolio', title: 'Portfolio', text: 'Positions, transactions, import from IBKR and breakdown by sector and currency.' },
  { href: '/risk', title: 'Exposures', text: 'Weights, concentration (top 1 and top 5) and exposure by sector and factor. It does not calculate VaR, drawdown or volatility: these are portfolio-structure metrics.' },
  { href: '/screeners', title: 'Screener', text: 'A universe of large caps with real profiles and prices, to start from verifiable candidates.' },
  { href: '/propicks', title: 'ProPicks', text: 'Scores from 0 to 100 with auditable reasons (each reason shows its metric and value) and a per-strategy backtest against the S&P 500.' },
  { href: '/alerts', title: 'Alerts', text: 'Signals with an explicit materiality threshold, linked to the company page.' },
  { href: '/insider', title: 'Insider', text: 'Trades by insiders (SEC Form 4) with signals for buying clusters.' },
  { href: '/knowledge', title: 'Library and search', text: 'A library of investing principles and a semantic index rebuilt from Postgres.' },
  { href: '/watchlist', title: 'Watchlist', text: 'Tracking of symbols with a direct link to their research page.' },
  { href: '/metodologia', title: 'Methodology', text: 'Valuation engines with their assumptions, data sources, limits (look-ahead, partial coverage) and explicit costs.' },
];

export const FAQS_EN = [
  { question: 'How much does GerarAI cost?', answer: 'The app is free to use: it does not have paid plans or charge anything. It runs on free-tier data providers (Finnhub, Yahoo Finance, SEC EDGAR), which limits the coverage and freshness of some data.' },
  { question: 'Is this financial advice?', answer: 'It is not. GerarAI is an analysis tool: models and theses depend on visible assumptions and can be wrong. Investment decisions are yours.' },
  { question: 'How do I follow a company?', answer: 'Open its page in Research and press «Follow», next to the name. The symbols you follow are collected in your watchlist.' },
  { question: 'What should I do if I find a bug or have a suggestion?', answer: 'Write to the address in the Contact tab, with the page and what you expected to see. A response time is not guaranteed.' },
  { question: 'Is market data real-time?', answer: 'Not real-time. Market data is delayed in most markets: it is meant for analysis, not intraday trading. In the watchlist and research, each price shows the date of its close.' },
];

export function LoginNoteEn() {
  return (
    <>
      The links to <span className={HI}>research</span>, <span className={HI}>portfolio</span>,{' '}
      <span className={HI}>risk</span>, <span className={HI}>ProPicks</span>, <span className={HI}>alerts</span>,{' '}
      <span className={HI}>insiders</span>, <span className={HI}>watchlist</span> and{' '}
      <span className={HI}>export</span> describe workspace modules and{' '}
      <strong className={HI}>require signing in</strong>. This help page and the methodology can be read without an account.
    </>
  );
}

export function FirstStepsEn() {
  return (
    <>
      <li>
        <strong className={STRONG}>1. Model.</strong>{' '}
        In <Link href="/research" className={LINK}>Research</Link> choose the company, open the «Model» tab and press
        «Generate model». Review the assumptions (growth, FCF margin, WACC) and the Bear/Base/Bull scenarios with their
        spreads before trusting the number.
      </li>
      <li>
        <strong className={STRONG}>2. Thesis.</strong>{' '}
        Generate the thesis from the same page: hypothesis, scenarios with probabilities, dated catalysts and what would
        invalidate it. The memo and the EPUB are exported from the thesis view itself («Export memo» and «Export EPUB»);{' '}
        <Link href="/export" className={LINK}>/export</Link> is the yearly export of the journal.
      </li>
      <li>
        <strong className={STRONG}>3. Decision.</strong>{' '}
        Record the decision in the Decision journal (Buy / Hold / Trim / Sell / Watch / Avoid) with the evidence behind it
        and the verifiable conditions («What must be true»). Later, «Expectations vs reality» compares your forecast with
        the published facts.
      </li>
    </>
  );
}

export function GlossaryEn() {
  return (
    <>
      Technical terms (DCF, WACC, reverse DCF, moat, margin of safety, look-ahead, owner earnings, TAM/SAM/SOM, ROIC,
      VaR, drawdown, Sharpe) carry a tooltip with their definition wherever they appear. The valuation engines with
      their assumptions, the data sources (Finnhub, Yahoo Finance, SEC EDGAR), the limits and the costs are documented
      in <Link href="/metodologia" className={LINK}>/metodologia</Link>.
    </>
  );
}
