/**
 * Titulares sin compañía asociada («Mercado general») solo se muestran si hablan
 * de mercados, economía o empresas. Los proveedores gratuitos mezclan noticias
 * de consumo o sucesos (crianza, helicópteros...) bajo la categoría "general".
 * Es una lista de términos explícita y determinista; no clasifica con un modelo.
 */
const FINANCE_TERMS = [
    'stock', 'stocks', 'share', 'shares', 'market', 'markets', 'wall street', 'nasdaq', 'dow', 's&p',
    'earnings', 'revenue', 'profit', 'guidance', 'ipo', 'dividend', 'buyback', 'merger', 'acquisition',
    'fed', 'federal reserve', 'interest rate', 'rates', 'inflation', 'cpi', 'jobs report', 'payrolls', 'gdp',
    'treasury', 'yield', 'bond', 'dollar', 'euro', 'oil', 'crude', 'gold', 'bitcoin', 'crypto',
    'tariff', 'recession', 'economy', 'economic', 'bank', 'investor', 'investors', 'etf', 'fund',
    'ceo', 'sec ', 'antitrust', 'chip', 'semiconductor', 'ai ', 'tesla', 'nvidia', 'apple', 'microsoft',
    'amazon', 'google', 'alphabet', 'meta ', 'bolsa', 'acciones', 'mercado', 'inflación', 'tipos de interés',
    'resultados', 'beneficio', 'ibex', 'bce',
];

const FINANCE_PATTERN = new RegExp(
    FINANCE_TERMS.map((term) => {
        const escaped = term.replace(/[.*+?^${}()|[\]\\&]/g, '\\$&');
        return /^[a-z]/i.test(term) ? `\\b${escaped.trim()}\\b` : escaped;
    }).join('|'),
    'i',
);

export function isFinanciallyRelevant(article: { headline?: string; summary?: string; related?: string | null }): boolean {
    if (article.related?.trim()) return true;
    return FINANCE_PATTERN.test(`${article.headline ?? ''} ${article.summary ?? ''}`);
}
