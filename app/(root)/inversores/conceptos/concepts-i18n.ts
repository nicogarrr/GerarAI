import type { Locale } from "@/lib/i18n/locale";
import { CONCEPTS, type InvestorConcept } from "./concepts";

/** Versión inglesa de la síntesis editorial (mismos slugs, mismas fuentes). */
type ConceptText = Pick<InvestorConcept, "title" | "summary" | "body" | "application" | "risk"> & {
  sourceTitle?: string;
};

const CONCEPTS_EN: Record<string, ConceptText> = {
  "circulo-de-competencia": {
    title: "Circle of competence",
    summary: "Understanding a business matters more than following every business.",
    body: "Buffett separates evaluating selected companies from knowing every company. What matters is defining what you understand, not widening the circle at any price.",
    application: "Before valuing a company, work out how it makes money, what sustains its advantage and what could change that business.",
    risk: "Knowing the product is not enough to understand its costs, debt or competition.",
    sourceTitle: "Berkshire Hathaway · 1996 letter",
  },
  "ventaja-competitiva": {
    title: "Durable competitive advantage",
    summary: "Looking for an economic position that can stand the test of time.",
    body: "The 1996 letter describes Berkshire's preference for businesses whose competitive strength can still exist many years later. The purchase price still matters.",
    application: "Test the advantage against margins, customer retention, switching costs and rivals' ability to copy it.",
    risk: "An excellent company can be a bad investment if you overpay. The advantage can also disappear.",
    sourceTitle: "Berkshire Hathaway · 1996 letter",
  },
  "paciencia": {
    title: "Patience and follow-up",
    summary: "Holding a good business does not mean you stop checking the thesis.",
    body: "Buffett compares holding shares to owning a business: buy at a sensible price and then check whether the economic quality and the quality of management are holding up.",
    application: "Define the signals that would invalidate the thesis before you buy. Review the business, not just its share-price swings.",
    risk: "Patience does not justify ignoring permanent deterioration or concentration risk.",
    sourceTitle: "Berkshire Hathaway · 1996 letter",
  },
  "opciones": {
    title: "Options: calls and puts",
    summary: "Rights for the buyer, obligations for the seller.",
    body: "A call gives the buyer the right to buy the underlying at the strike price; a put, the right to sell it. The right has an expiry date and costs a premium. The seller takes on the matching obligation when it is exercised.",
    application: "Compare the premium, the expiry, the strike price and the real contract size before opening a position.",
    risk: "The buyer can lose the whole premium. Selling options can require margin and lead to losses larger than the premium collected; an uncovered (naked) short call can have unlimited losses.",
    sourceTitle: "SEC · Introduction to options",
  },
  "wacc": {
    title: "WACC (weighted average cost of capital)",
    summary: "The minimum return demanded by the capital invested in the company.",
    body: "WACC weights the cost of equity and the cost of debt by their share of the financing. It is the rate used to discount future cash flows and the bar ROIC must clear for the company to create value. It is an estimate built on assumptions (risk-free rate, beta, equity risk premium, cost of debt) that are worth knowing before comparing.",
    application: "Compare ROIC with WACC before talking about value creation, and check the assumptions behind any WACC you use as a discount rate.",
    risk: "Two serious analysts get different WACCs for the same company: a different beta or risk premium changes the valuation.",
  },
  "cfroi": {
    title: "CFROI",
    summary: "Cash flow return on the gross investment made.",
    body: "CFROI (cash flow return on investment) estimates the return on investment from its cash flows. Its full formulation uses an internal rate of return on gross investment, adjusted for inflation and the useful life of the assets. It is more than cash flow divided by assets. Approximations should state their formula and limits before being compared with the cost of capital.",
    application: "A CFROI that stays above the cost of capital signals value creation; below it, the company destroys value even if accounting profit grows.",
    risk: "Approximations are not comparable with each other or with the original CFROI unless the exact formula used is known.",
  },
  "foso-competitivo": {
    title: "Economic moat",
    summary: "The advantage that protects profits from competition for years.",
    body: "In 2007 Buffett asked for businesses with a durable moat: a barrier that makes it hard for competitors to erode their returns. Brand, lower costs, switching costs, network effects, licences or capital barriers are common forms. A moat is more than a list of qualities: it is the answer to why this business will still be making money ten years from now.",
    application: "Before valuing, identify the company's moat, the evidence for it (retention, stable margins, market share) and what could erode it.",
    risk: "Moats narrow: technology, regulation or poor management can remove an advantage that looked permanent.",
    sourceTitle: "Berkshire Hathaway · 2007 letter",
  },
  "owner-earnings": {
    title: "Owner earnings",
    summary: "The cash the owner can take out without harming the business.",
    body: "Owner earnings, described by Buffett in 1986, start from reported earnings, add depreciation, amortization and certain other non-cash charges, and subtract the average capital spending needed to maintain the business's competitive position and unit volume, including any extra working capital it needs. Maintenance spending takes judgement and is rarely disclosed separately. It is neither automatically FCF nor net income plus D&A minus total capex.",
    application: "Use it instead of net income when assessing how much cash a business really generates for its owner.",
    risk: "If the maintenance capex estimate is too low, owner earnings are inflated without anyone lying.",
    sourceTitle: "Berkshire Hathaway · 1986 letter",
  },
  "capex-mantenimiento-crecimiento": {
    title: "Maintenance vs. growth capex",
    summary: "Investment comes in two kinds: part maintains the business and part expands it.",
    body: "Maintenance capex aims to preserve current capacity and competitive position; growth capex aims to expand them. Both are cash outflows and can be capitalised in the accounts. Separating them helps estimate the cash the business would generate without expansion, but a universal rule does not exist: many companies do not disclose the split. D&A can serve as a proxy; it does not prove how much maintenance the business needs.",
    application: "When a company invests heavily, ask which part maintains what already exists and which part builds something new with an expected return.",
    risk: "A business that has to reinvest everything just to stand still looks like it is growing when it is really running to stay in the same place.",
    sourceTitle: "Berkshire Hathaway · 1986 letter",
  },
  "trampa-de-valor": {
    title: "Value trap",
    summary: "Cheap on multiples is not cheap if the business is deteriorating.",
    body: "A value trap is a stock trading on low multiples because the market is pricing in permanent deterioration: falling earnings, a vanishing moat, crushing debt. The low multiple may reflect a decline the initial valuation missed. To tell it apart from a bargain, check that cash generation and competitive position are holding up.",
    application: "Before buying something very cheap, look for the reason for the discount and check whether the deterioration is temporary or permanent.",
    risk: "A big fall in a share price is evidence of nothing: it may be cheap or it may be starting to price in its decline.",
  },
  "ciclo-economico": {
    title: "Business cycle",
    summary: "The phases of expansion and contraction the whole economy goes through.",
    body: "Activity, employment and corporate profits move in cycles with neither a fixed length nor a predictable calendar. Cyclical companies amplify that swing; defensive ones dampen it. The cycle matters for valuation: applying a multiple to peak-cycle earnings permanently overstates what the company can earn.",
    application: "For cyclical companies, normalise earnings over a full cycle before comparing multiples.",
    risk: "Mistaking a cyclical peak for structural growth leads to paying growth prices for cyclical businesses.",
    sourceTitle: "Wikipedia · Business cycle (in Spanish)",
  },
  "curva-de-tipos": {
    title: "Yield curve",
    summary: "The yield on government debt by maturity, and what it anticipates.",
    body: "The yield curve relates the yields and maturities of comparable debt instruments on a given date. For government debt, a single issuer or a consistent benchmark curve is usually used. It can slope upwards, be flat or be inverted. It reflects expectations of future rates plus term and risk premiums. An inverted curve is not a reliable recession timetable.",
    application: "Use it as context: an inverted curve makes short-term funding more expensive and tends to coincide with tight monetary policy.",
    risk: "Predicting recessions with the curve racks up false positives; it is context, not a calendar.",
    sourceTitle: "Wikipedia · Yield curve (in Spanish)",
  },
  "deflacion": {
    title: "Deflation",
    summary: "A sustained fall in prices that makes debts heavier.",
    body: "Deflation is a sustained fall in the general price level, unlike disinflation, which is a slower rate of increase. It can come from weak demand or from supply and productivity gains; its effects depend on the cause. It can raise the real burden of nominal debts and, when people expect it to continue, delay some spending. A one-off price cut on a single product does not prove deflation.",
    application: "In a deflationary environment debt weighs more every year: it demands more real cash from indebted companies and households.",
    risk: "Mistaking deflation for disinflation (prices rising more slowly) completely changes the diagnosis.",
    sourceTitle: "Wikipedia · Deflation (in Spanish)",
  },
  "bancos-centrales": {
    title: "Central banks",
    summary: "The institutions that set the official price of money.",
    body: "A central bank issues the currency, sets official interest rates and pursues price and financial stability; in the euro area it is the ECB and in the United States the Federal Reserve. Its decisions feed through to the cost of debt, asset valuations and inflation. Knowing its mandate helps explain why rates go up or down.",
    application: "Follow official rates and the central bank's guidance as valuation context: they affect the discount rate of everything else.",
    risk: "Formal independence does not rule out misdiagnoses; its forecasts also miss.",
    sourceTitle: "Banco de España · What is a central bank? (in Spanish)",
  },
  "compounder": {
    title: "Compounder",
    summary: "The company that reinvests well, again and again.",
    body: "A compounder is a company able to reinvest its earnings at high returns for many years, so that its value grows at a compound rate. The key is more than growth: every euro retained has to earn more than its cost of capital. Buffett summed up the idea in 1989: time is the friend of the wonderful business and the enemy of the mediocre.",
    application: "Look for businesses with a high ROIC and room to reinvest; that is where compounding works for the shareholder.",
    risk: "Paying any price for a compounder destroys the advantage, and past growth does not guarantee future room to reinvest.",
    sourceTitle: "Berkshire Hathaway · 1989 letter",
  },
  "spin-off": {
    title: "Spin-off",
    summary: "A subsidiary that becomes independent by handing shares to shareholders.",
    body: "In a spin-off, a company separates a division into an independent company and distributes its shares to existing shareholders, usually at zero cost to them. The stated reason is usually to give each business focus and let the market value them separately. It creates or destroys value depending on the quality of what is spun off, the debt loaded onto it and the terms of the deal.",
    application: "When a company in your portfolio announces a spin-off, read the prospectus: which business is leaving, with how much debt and with which team.",
    risk: "Receiving shares is not a gift: the parent's price adjusts, and some spin-offs are used to offload debt or problems.",
  },
  "asignacion-de-capital": {
    title: "Capital allocation",
    summary: "What the company does with the cash it generates.",
    body: "Capital allocation is the choice between reinvesting, paying down debt, paying dividends, buying back shares or buying other companies. Built up over years, it explains much of shareholder returns. It is judged by comparing the return on each euro deployed with the alternatives, not by the size or noise of the deals.",
    application: "Assess management by its capital allocation track record: it is their main job once the business works.",
    risk: "A single large, expensive acquisition can wipe out years of good business; the buyer's ego only shows up in the accounts later.",
  },
  "poder-de-precios": {
    title: "Pricing power",
    summary: "Raising prices without lost demand cancelling out the gain.",
    body: "Pricing power is a company's ability to raise prices without losing enough demand to hurt profitability. It can rest on differentiation, switching costs or other barriers, and it has limits. Prices, volumes, competition and margins are best checked together. Passing a cost increase on to customers can show it, but a price rise on its own does not prove it.",
    application: "Check whether the company raised prices in years of cost inflation and what happened to its volumes and margins.",
    risk: "Pricing power has limits: abusing it attracts competitors, regulators or substitutes.",
  },
  "segundas-derivadas": {
    title: "Second-order effects",
    summary: "The consequences of the consequences.",
    body: "Second-order thinking means asking what the first consequences of an event will set off. A rate rise makes debt more expensive; at the second order, it reduces buybacks, puts pressure on real estate and changes public spending. The market usually prices in the first-order effect quickly; the analytical edge lies in mapping the next ones without inventing certainty about their size.",
    application: "When news breaks, write down the chain: the first-order effect, then what that changes in the businesses you follow.",
    risk: "Second-order chains multiply assumptions; each link adds uncertainty, not certainty.",
  },
  "efecto-ricardo": {
    title: "Ricardo effect",
    summary: "How relative costs shape the substitution between labour and capital.",
    body: "The Ricardo effect links the relative cost of labour and capital to the choice between more labour-intensive or more machine-intensive methods: if labour becomes relatively more expensive, it may pay to replace it with capital, and vice versa. How the mechanism fits into Austrian business cycle theory is debated. It should not be confused with Ricardian equivalence on taxes and public debt.",
    application: "Use it to analyse the substitution between labour and machinery when their relative costs change.",
    risk: "Its role in cycle theory is debated and depends on assumptions; it is neither a valuation tool nor the same thing as Ricardian equivalence.",
  },
};

function localize(concept: InvestorConcept, locale: Locale): InvestorConcept {
  const en = locale === "en" ? CONCEPTS_EN[concept.slug] : undefined;
  if (!en) return concept;
  const { sourceTitle, ...text } = en;
  return { ...concept, ...text, source: { ...concept.source, title: sourceTitle ?? concept.source.title } };
}

/** Conceptos en el idioma elegido (español por defecto). */
export function conceptsFor(locale: Locale): InvestorConcept[] {
  return CONCEPTS.map((concept) => localize(concept, locale));
}

export function conceptsForInvestorIn(slug: string, locale: Locale): InvestorConcept[] {
  return conceptsFor(locale).filter((concept) => concept.investors.includes(slug));
}
