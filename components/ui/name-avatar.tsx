'use client';

import { useT } from '@/lib/i18n/client';
import Image from "next/image"

import { avatarInitials, avatarTone } from "@/lib/ui/avatar-color"
import { cn } from "@/lib/utils"

type NameAvatarProps = {
    name: string
    /** Foto con licencia verificada; sin ella se pintan iniciales con color estable. */
    photoSrc?: string | null
    photoTitle?: string
    className?: string
}

/** Avatar de persona o empresa: foto si hay, iniciales con color estable si no. */
export function NameAvatar({ name, photoSrc, photoTitle, className }: NameAvatarProps) {
    const t = useT();
    const box = cn("size-11 shrink-0 rounded-full", className)
    if (photoSrc) {
        return (
            <Image
                alt={t('ui.nameAvatar.photo', { name })}
                className={cn(box, "object-cover object-top")}
                height={64}
                src={photoSrc}
                title={photoTitle}
                width={64}
            />
        )
    }
    return (
        <span
            aria-hidden="true"
            className={cn(
                box,
                "flex items-center justify-center text-sm font-semibold",
                avatarTone(name),
            )}
        >
            {avatarInitials(name)}
        </span>
    )
}
