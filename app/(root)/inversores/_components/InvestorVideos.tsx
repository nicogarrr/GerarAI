'use client';

import Link from 'next/link';
import { YouTubeEmbed } from '@/components/media/YouTubeEmbed';
import { useLocale, useT } from '@/lib/i18n/client';
import { validInvestorVideos } from '@/lib/ui/youtube-video';

const DATE_OPTIONS: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' };

export function InvestorVideos({ videos }: { videos?: unknown }) {
    const t = useT();
    const locale = useLocale();
    const dateFormat = new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'es-ES', DATE_OPTIONS);
    const items = validInvestorVideos(videos);
    return (
        <section aria-labelledby="investor-videos-title" className="flex flex-col gap-4 border-t border-gray-800 pt-6">
            <h2 className="text-xl font-semibold text-gray-100" id="investor-videos-title">{t('investors.videos.title')}</h2>
            {items.length === 0 ? <div className="rounded-lg border border-gray-800 p-4">
                <p className="text-sm font-medium text-gray-300">{t('investors.videos.empty')}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                    <Link href="/inversores/canales" className="inline-flex min-h-11 items-center rounded-lg border border-gray-700 px-3 text-sm text-teal-300">{t('investors.videos.seeChannels')}</Link>
                </div>
            </div> : (
                <ul className="grid gap-6 sm:grid-cols-2">
                    {items.map((video) => (
                        <li className="flex min-w-0 flex-col gap-2" key={video.video_id}>
                            <YouTubeEmbed title={video.title} videoId={video.video_id} />
                            {video.channel_kind === 'archive' ? <p className="text-xs text-gray-400">{t('investors.videos.archive')}</p> : null}
                            <h3 className="text-sm font-medium text-gray-200">{video.title}</h3>
                            <p className="text-xs text-gray-500">
                                <time dateTime={video.published_at}>{dateFormat.format(new Date(video.published_at))}</time>
                                {` · ${t('investors.videos.source')} `}
                                <a className="underline-offset-2 hover:underline" href={video.channel_url} rel="noreferrer" target="_blank">{video.channel_name}</a>
                            </p>
                            <a className="text-xs text-gray-400 underline-offset-2 hover:underline" href={`https://www.youtube.com/watch?v=${video.video_id}`} rel="noreferrer" target="_blank">{t('investors.videos.watchOnYoutube')}</a>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}
