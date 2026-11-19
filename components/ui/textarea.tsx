import * as React from "react"

import { cn } from "@/lib/utils"

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
    ({ className, ...props }, ref) => {
        return (
            <textarea
                className={cn(
                    "flex min-h-[80px] w-full rounded-lg border border-gray-600 bg-transparent px-4 py-2 text-base transition-all duration-200 outline-none dark:bg-gray-800/50 placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
                    "focus-visible:border-teal-400 focus-visible:bg-gray-800 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-0",
                    "aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Textarea.displayName = "Textarea"

export { Textarea }
