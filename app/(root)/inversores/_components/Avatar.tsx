import { NameAvatar } from '@/components/ui/name-avatar';
import { getT } from '@/lib/i18n/server';

import { INVESTOR_PHOTOS } from './photos';

/** Foto con licencia libre verificada (ver photos.ts); si no la hay, iniciales con color estable por nombre. */
export async function InvestorAvatar({ name, slug, size = 'md' }: { name: string; slug?: string; size?: 'md' | 'lg' }) {
    const photo = slug ? INVESTOR_PHOTOS[slug] : undefined;
    const t = await getT();
    return (
        <NameAvatar
            className={size === 'lg' ? 'size-16 text-xl' : 'size-11 text-sm'}
            name={name}
            photoSrc={photo?.src}
            photoTitle={photo ? `${t('investors.detail.photo')} ${photo.author}, ${photo.license}, ${t('investors.detail.via')} Wikimedia Commons` : undefined}
        />
    );
}
