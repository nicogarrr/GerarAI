/**
 * Mensajes del motor que llegan en castellano y tienen traducción conocida
 * (Ajustes → Idioma = English). Solo frases fijas del propio motor —rutas y
 * validaciones de cartera, importación, plan, alertas y paper trading—; un
 * texto que no está aquí pasa intacto (no se traduce prosa a ciegas). Los
 * valores entre comillas o números del mensaje se conservan tal cual.
 */
const KNOWN: ReadonlyArray<readonly [RegExp, string]> = [
  // Rutas
  [/^El parámetro offset solo tiene efecto junto a limit\.?$/, 'The offset parameter only works together with limit.'],
  [/^El parámetro offset no aplica aquí; usa \/transactions\/page o page\/page_size\.?$/, 'The offset parameter does not apply here; use /transactions/page or page/page_size.'],
  [/^rango máximo: (\d+) días$/i, 'Maximum range: $1 days.'],
  [/^Ya existe una cartera con este nombre para el usuario\.?$/, 'A portfolio with this name already exists.'],
  [/^Fecha fuera de rango\.?$/i, 'Date out of range.'],
  [/^El archivo supera el máximo de (\d+) MB para importación\.?$/, 'The file exceeds the $1 MB import limit.'],
  [/^Usa el conector IBKR de Ajustes para esta cartera\.?$/, 'Use the IBKR connector in Settings for this portfolio.'],
  [/^Servicio de audio no disponible\.?$/, 'Audio service not available.'],
  [/^Audio no generado\.?$/, 'Audio not generated.'],
  [/^Noticia no encontrada\.?$/, 'News item not found.'],
  [/^Introduce una API key para probar la conexión\.?$/, 'Enter an API key to test the connection.'],
  [/^Radar Yahoo no disponible ahora mismo; no se han generado candidatos\.?$/, 'Yahoo radar not available right now; no candidates were generated.'],
  // Importación de operaciones (CSV/Excel genérico)
  [/^La fecha no puede estar vacía\.?$/, 'The date cannot be empty.'],
  [/^La fecha de operación no puede ser futura \((.+)\)$/, 'The trade date cannot be in the future ($1).'],
  [/^Formato de fecha irreconocible: (.+)$/, 'Unrecognised date format: $1'],
  [/^Divisa no reconocida: (.+) \(se esperaba un código como EUR, USD o GBp\)$/, 'Unrecognised currency: $1 (expected a code such as EUR, USD or GBp)'],
  [/^Tipo de operación no reconocido: (.+) \(se esperaba compra, venta o dividendo\)$/, 'Unrecognised transaction type: $1 (expected buy, sell or dividend)'],
  [/^El archivo Excel no contiene filas con datos\.?$/, 'The Excel file has no rows with data.'],
  [/^No se pudo decodificar el archivo como texto \(se esperaba UTF-8 o Latin-1\)$/, 'The file could not be decoded as text (expected UTF-8 or Latin-1)'],
  [/^El archivo CSV está vacío\.?$/, 'The CSV file is empty.'],
  [/^El archivo CSV no contiene registros válidos\.?$/, 'The CSV file has no valid records.'],
  [/^No hay transacciones para importar\.?$/, 'There are no transactions to import.'],
  // Plan de inversión
  [/^El importe de la aportación debe ser positivo con precisión de céntimos\.?$/, 'The contribution amount must be positive, with cent precision.'],
  [/^La fecha de la aportación no puede ser futura\.?$/, 'The contribution date cannot be in the future.'],
  [/^La etiqueta del objetivo no puede estar vacía\.?$/, 'The target label cannot be empty.'],
  // Importar cartera desde imagen
  [/^Falta la sesión de cartera$/, 'The portfolio session is missing.'],
  [/^Revisa las filas: no se permiten instrumentos repetidos$/, 'Check the rows: repeated instruments are not allowed.'],
  [/^Confirma instrumento, cantidad y divisa de cada fila$/, 'Confirm the instrument, quantity and currency of each row.'],
  [/^(\S+): elige un instrumento identificado en el catálogo$/, '$1: choose an instrument identified in the catalogue.'],
  [/^(\S+): la divisa no coincide con el instrumento$/, "$1: the currency does not match the instrument."],
  [/^(\S+): ya existe en tu cartera o historial\. Usa el fichero del bróker para conciliar; no se sumará ni sobrescribirá$/, "$1: already in your portfolio or history. Use the broker's file to reconcile; it will not be added or overwritten."],
  [/^La consulta de precios tardó demasiado\. Revisa menos filas a la vez o vuelve a intentarlo$/, 'The price lookup took too long. Review fewer rows at a time or try again.'],
  [/^Confirma la revisión antes de guardar$/, 'Confirm the review before saving.'],
  [/^La revisión no existe en tu cartera$/, 'The review does not exist in your portfolio.'],
  [/^Faltan cotizaciones o la revisión ha caducado\. Vuelve a revisar$/, 'Quotes are missing or the review has expired. Review again.'],
  [/^Cotización caducada\. Vuelve a revisar$/, 'Quote expired. Review again.'],
  // Conexión IBKR (Ajustes)
  [/^Inicia sesión para configurar IBKR\.?$/, 'Sign in to set up IBKR.'],
  [/^Revisa el token Flex: debe contener solo números\.?$/, 'Check the Flex token: it must contain only digits.'],
  [/^Revisa el Query ID de tu consulta Flex\.?$/, 'Check the Query ID of your Flex query.'],
  [/^Introduce la cuenta IBKR tal como figura en el extracto\.?$/, 'Enter the IBKR account exactly as it appears on the statement.'],
  [/^Esta cartera ya está vinculada a otra cuenta IBKR\. No se pueden mezclar cuentas en esta versión\.?$/, 'This portfolio is already linked to another IBKR account. Accounts cannot be mixed in this version.'],
  [/^La cuenta no coincide con la fuente IBKR existente de esta cartera\.?$/, "The account does not match this portfolio's existing IBKR source."],
  [/^El CSV está mal formado y no se puede leer; expórtalo de nuevo desde IBKR$/, 'The CSV is malformed and cannot be read; export it again from IBKR.'],
  // Importación de operaciones (más)
  [/^El archivo CSV está mal formado y no se puede leer; guárdalo de nuevo como CSV \(UTF-8\)$/, 'The CSV file is malformed and cannot be read; save it again as CSV (UTF-8).'],
  [/^Error al leer el archivo Excel: (.+)$/, 'Error reading the Excel file: $1'],
  [/^La fecha de operación es anterior a (\d{4}) \((.+)\): revisa el año$/, 'The trade date is before $1 ($2): check the year.'],
  // Importar cartera desde imagen (más)
  [/^La imagen debe ocupar como máximo 2 MB$/, 'The image must be 2 MB at most.'],
  [/^Usa una imagen PNG, JPEG o WebP sin animación$/, 'Use a PNG, JPEG or WebP image without animation.'],
  [/^La imagen debe tener entre 100 píxeles de lado y 12 megapíxeles$/, 'The image must be between 100 pixels per side and 12 megapixels.'],
  [/^No se pudo iniciar la lectura local\. Usa un fichero o la entrada manual$/, 'Local reading could not start. Use a file or manual entry.'],
  [/^No se pudo leer la captura\. Prueba con un recorte más nítido o importa un fichero$/, 'The screenshot could not be read. Try a sharper crop or import a file.'],
  [/^La captura contiene demasiado texto\. Recorta solo la tabla de posiciones$/, 'The screenshot has too much text. Crop just the positions table.'],
  // Watchlist, plan, impuestos y asistente
  [/^La etiqueta no puede llevar saltos de línea ni caracteres de control$/, 'The label cannot contain line breaks or control characters.'],
  [/^Los objetivos de tipo (\S+) suman ([\d.,]+) %: no pueden superar el 100 %\.?$/, '$1 targets add up to $2%: they cannot exceed 100%.'],
  [/^El NIF contiene caracteres de control no imprimibles\.?$/, 'The tax ID (NIF) contains non-printable control characters.'],
  [/^El modo guía requiere un ticker$/, 'Guide mode needs a ticker.'],
  [/^El ticket requiere un ticker$/, 'The ticket needs a ticker.'],
  // Alertas y paper trading
  [/^El umbral de una alerta de precio o de cambio debe ser un número\.?$/, 'The threshold of a price or change alert must be a number.'],
  [/^El precio de la alerta debe ser mayor que 0\.?$/, 'The alert price must be greater than 0.'],
  [/^El número debe ser finito\.?$/, 'The number must be finite.'],
  [/^El número excede la precisión persistida\.?$/, 'The number exceeds the stored precision.'],
  [/^Número fuera de la precisión persistida\.?$/, 'Number outside the stored precision.'],
  [/^Long: stop < entrada propuesta < objetivo$/, 'Long: stop < proposed entry < target'],
  [/^Short: objetivo < entrada propuesta < stop$/, 'Short: target < proposed entry < stop'],
];

/** Traducción inglesa de un mensaje fijo del motor; `null` si no es uno conocido. */
export function knownBackendMessageEn(text: string): string | null {
  // Pydantic antepone «Value error, » a los ValueError de validación.
  const body = text.replace(/^Value error,\s*/i, '');
  for (const [pattern, english] of KNOWN) {
    if (pattern.test(body)) return body.replace(pattern, english);
  }
  return null;
}
