/** Nombres de presentación; el CIK y el nombre oficial de SEC no se alteran. */
// Import relativo con atributo: este módulo también se ejecuta en tests con
// node --experimental-strip-types, que no resuelve el alias `@/`.
import esOwnership from './i18n/messages/es/ownership.json' with { type: 'json' };
import enOwnership from './i18n/messages/en/ownership.json' with { type: 'json' };

const MANAGER_NAMES: Record<string, string> = {
  '0001067983': 'Berkshire Hathaway',
  '0002026053': 'Pershing Square',
  '0001709323': 'Himalaya Capital',
  '0000783412': 'Daily Journal',
  '0001549575': 'Dalal Street',
  '0001112520': 'Akre Capital Management',
  '0001061768': 'Baupost Group',
  '0001536411': 'Duquesne Family Office',
  '0001656456': 'Appaloosa',
  '0001040273': 'Third Point',
  '0001056831': 'Fairholme Capital',
  '0000732905': 'Tweedy, Browne',
  '0000813917': 'Harris Associates',
  '0001345471': 'Trian Fund Management',
  '0001061165': 'Lone Pine Capital',
  '0000807985': 'Southeastern',
  '0001167483': 'Tiger Global Management',
  '0001034524': 'Polen Capital',
  '0001569205': 'Fundsmith',
  '0001096343': 'Markel Group',
  '0001166559': 'Gates Foundation Trust',
  '0001317588': 'Abrams Bison Investments',
  '0001376879': 'AKO Capital',
  '0001063296': 'Atlantic Investment Management',
  '0001350694': 'Bridgewater Associates',
  '0000921669': 'Carl Icahn',
  '0001029160': 'Soros Fund Management',
  '0001135730': 'Coatue Management',
  '0001103804': 'Viking Global Investors',
};

export function ownershipManagerName(cik: string, officialName: string): string {
  return MANAGER_NAMES[cik] ?? officialName;
}

/**
 * Aviso para un 13F servido sin verificar (Auditoría A): la API ya no dice
 * «ok» cuando los totales no cuadran con el resumen del propio filing o no se
 * pudieron contrastar. Las cifras se muestran, pero nunca como verificadas.
 * Los textos viven en los diccionarios (ownership.verification.*).
 */
const VERIFICATION_KEYS = ['mismatch', 'unverified', 'partial', 'snapshot'] as const;
// Uso por literal para el guard de i18n (claves consumidas por iteración).
export const OWNERSHIP_VERIFICATION_KEY_LITERALS = [
    'ownership.verification.mismatch',
    'ownership.verification.unverified',
    'ownership.verification.partial',
    'ownership.verification.snapshot',
] as const;
const VERIFICATION_NOTE_EN: Record<string, string> = enOwnership.verification;
const VERIFICATION_NOTE_ES: Record<string, string> = esOwnership.verification;

export function holdingsVerificationNote(status: string, locale: 'es' | 'en' = 'es'): string | null {
  const table = locale === 'en' ? VERIFICATION_NOTE_EN : VERIFICATION_NOTE_ES;
  return table[status] ?? null;
}
