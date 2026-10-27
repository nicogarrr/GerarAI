import localFont from "next/font/local";

// Solo los shells público/auth importan estas fuentes. La app conserva su sans.
export const publicSans = localFont({
  src: "../app/fonts/Manrope-Variable.woff2",
  weight: "200 800",
  display: "swap",
  preload: true,
});

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
