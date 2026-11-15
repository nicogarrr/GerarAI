/** Screenshot transcription, not company results, consensus or valuation inputs. */
export const ASTS_BANK_SUPPLEMENT = {
  receivedOn: '2026-11-15',
  reportDate: null,
  originalReportUrl: null,
  verification: 'unverified_screenshot',
  attributedTo: 'Deutsche Bank',
  currency: 'USD',
  unit: 'millions',
  socialMirrorUrl: 'https://lunarcrush.ai/topic/$asts/posts',
  blackliftPrimaryUrl: 'https://www.sec.gov/Archives/edgar/data/1780312/000149315226050513/ex99-1.htm',
  rows: [
    { year: 2025, revenue: 70.9, adjustedEbitda: -189.1, fcf: -1136.3, capex: null, satellites: null },
    { year: 2026, revenue: 163.6, adjustedEbitda: -315.2, fcf: -1936.1, capex: 1584.2, satellites: 15 },
    { year: 2027, revenue: 556.8, adjustedEbitda: -17.1, fcf: -1934.9, capex: null, satellites: 65 },
    { year: 2028, revenue: 1685.2, adjustedEbitda: 996.3, fcf: -701.5, capex: null, satellites: 125 },
    { year: 2029, revenue: 3140.8, adjustedEbitda: 2351.9, fcf: 19.3, capex: null, satellites: 215 },
    { year: 2030, revenue: 4490.3, adjustedEbitda: 3606.5, fcf: 683.4, capex: null, satellites: 340 },
  ],
} as const;
