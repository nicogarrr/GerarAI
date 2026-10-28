import localFont from "next/font/local";

// Serif editorial de la landing y la vista de lectura de tesis. Modulo
// separado de `public-fonts.ts`: /sign-in y /sign-up importan la sans y no
// deben descargar ni precargar esta (test e2e/public-font-loading).
export const publicEditorial = localFont({
  src: "../app/fonts/InstrumentSerif.woff2",
  variable: "--font-editorial",
  weight: "400",
  // Cargar pronto, sin sustituir la tipografía tras el primer pintado:
  // una descarga lenta no debe mover el título y los botones de la landing.
  display: "optional",
  preload: true,
  adjustFontFallback: "Times New Roman",
});
