'use client';
import Link from 'next/link';
import ReactMarkdown from 'react-markdown';

/** Respuesta del chat de empresa con fuentes. El motor emite markdown ligero
    (**negrita**, listas con «-», enlaces); pintado como texto plano se veían
    los asteriscos literales («**NVDA · NVIDIA Corp**»). Mismo contrato visual
    que el Cerebro (components/brain/GlobalBrain.tsx): negrita, listas y
    enlaces internos con next/link sin recargar la app. */
export default function ChatAnswerMarkdown({ text }: { text: string }) {
  return (
    <div className="text-sm leading-7 text-gray-300 [&>p]:my-1">
      <ReactMarkdown
        // Nunca imágenes de la respuesta: una URL de imagen del motor sería una
        // petición remota al cargar la ficha (rastreo/exfiltración por URL).
        disallowedElements={['img']}
        components={{
          strong: ({ node, ...props }) => <strong className="font-semibold text-gray-100" {...props} />,
          ul: ({ node, ...props }) => <ul className="list-disc space-y-1 pl-5" {...props} />,
          li: ({ node, ...props }) => <li className="text-gray-300" {...props} />,
          a: ({ node, href, children, ...props }) =>
            href && href.startsWith('/') ? (
              <Link href={href} className="text-teal-300 underline underline-offset-2 hover:text-teal-200">
                {children}
              </Link>
            ) : (
              <a href={href} target="_blank" rel="noopener noreferrer" className="text-teal-300 underline underline-offset-2 hover:text-teal-200" {...props}>
                {children}
              </a>
            ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
