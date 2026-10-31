/** Nombres de presentación; el CIK y el nombre oficial de SEC no se alteran. */
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
};

export function ownershipManagerName(cik: string, officialName: string): string {
  return MANAGER_NAMES[cik] ?? officialName;
}

/**
 * Aviso para un 13F servido sin verificar (Auditoría A): la API ya no dice
 * «ok» cuando los totales no cuadran con el resumen del propio filing o no se
 * pudieron contrastar. Las cifras se muestran, pero nunca como verificadas.
 */
export function holdingsVerificationNote(status: string): string | null {
  if (status === 'mismatch') {
    return 'Los totales guardados no cuadran con el resumen del propio 13F: cifras sin verificar.';
  }
  if (status === 'unverified') {
    return 'No se pudo leer el resumen del 13F para contrastar los totales: cifras sin verificar.';
  }
  if (status === 'partial') {
    return 'Datos parciales: parte del informe no se pudo descargar o verificar.';
  }
  if (status === 'snapshot') {
    return 'Cifras servidas desde una copia local (snapshot) sin contrastar contra el 13F: sin verificar.';
  }
  return null;
}
