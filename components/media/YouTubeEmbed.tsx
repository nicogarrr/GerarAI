'use client';

import Image from 'next/image';
import { useState } from 'react';
import { Play } from 'lucide-react';

import { isYouTubeVideoId } from '@/lib/ui/youtube-video';

export function YouTubeEmbed({ videoId, title }: { videoId: string; title: string }) {
    const [loaded, setLoaded] = useState(false);
    if (!isYouTubeVideoId(videoId)) return null;

    return (
        <div className="relative aspect-video overflow-hidden rounded-xl bg-gray-900">
            {loaded ? (
                <iframe
                    allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture; web-share"
                    allowFullScreen
                    className="absolute inset-0 size-full border-0"
                    referrerPolicy="strict-origin-when-cross-origin"
                    src={`https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1`}
                    title={title}
                />
            ) : (
                <button
                    aria-label={`Reproducir: ${title}`}
                    className="group absolute inset-0 size-full focus-visible:outline-2 focus-visible:outline-offset-[-4px] focus-visible:outline-teal-300"
                    onClick={() => setLoaded(true)}
                    type="button"
                >
                    <Image alt="" className="object-cover" fill sizes="(max-width: 640px) 100vw, 448px" src={`https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`} />
                    <span className="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-black/35">
                        <span className="flex size-12 items-center justify-center rounded-full bg-teal-300 text-gray-950">
                            <Play aria-hidden="true" className="size-5" fill="currentColor" />
                        </span>
                    </span>
                </button>
            )}
        </div>
    );
}
