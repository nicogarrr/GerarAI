"use client"

import { Toaster as Sonner, ToasterProps } from "sonner"

// Sin next-themes a proposito: el layout fuerza `class="dark"` y sonner
// funciona sin provider. Tema fijo oscuro para no arrastrar dependencia.
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      position="top-center"
      className="toaster group"
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
        } as React.CSSProperties
      }
      {...props}
    />
  )
}

export { Toaster }
