import localFont from "next/font/local";

// Solo los shells público/auth importan esta fuente. La app conserva su sans.
export const publicSans = localFont({
  src: "../app/fonts/Manrope-Variable.woff2",
  weight: "200 800",
  display: "swap",
  preload: true,
});
