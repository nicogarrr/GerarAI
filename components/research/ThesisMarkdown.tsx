import { cleanThesisMarkdown } from '@/lib/research/thesis-text';
import { thesisCodeLabel } from '@/lib/research/thesis-code-label';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** Mapa de componentes markdown -> estilos de la app, compartido por el
 *  memorando de tesis y otros visores (fragmentos de conocimiento). */
export const markdownComponents: Components = {
          h1: ({ node: _node, ...props }) => (
            <h1 className="mb-3 text-lg font-semibold text-gray-100" {...props} />
          ),
          h2: ({ node: _node, ...props }) => (
            <h2 className="mb-2 mt-5 border-b border-gray-800 pb-1 text-base font-semibold text-gray-100 first:mt-0" {...props} />
          ),
          h3: ({ node: _node, ...props }) => (
            <h3 className="mb-1.5 mt-4 text-sm font-semibold text-gray-200" {...props} />
          ),
          h4: ({ node: _node, ...props }) => (
            <h4 className="mb-1 mt-3 text-sm font-semibold text-gray-200" {...props} />
          ),
          p: ({ node: _node, ...props }) => <p className="mb-2 last:mb-0" {...props} />,
          ul: ({ node: _node, ...props }) => (
            <ul className="mb-2 list-disc space-y-1 pl-5" {...props} />
          ),
          ol: ({ node: _node, ...props }) => (
            <ol className="mb-2 list-decimal space-y-1 pl-5" {...props} />
          ),
          strong: ({ node: _node, ...props }) => (
            <strong className="font-semibold text-gray-100" {...props} />
          ),
          a: ({ node: _node, ...props }) => (
            <a
              className="break-all text-teal-400 underline"
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            />
          ),
          code: ({ node: _node, className, ...props }) => (
            <code
              className={`rounded bg-gray-800 px-1 py-0.5 font-mono text-[0.85em] text-gray-200 ${className ?? ''}`}
              {...props}
            />
          ),
          pre: ({ node: _node, ...props }) => (
            <pre className="mb-2 min-w-0 max-w-full overflow-x-auto rounded-lg bg-gray-900 p-3" {...props} />
          ),
          blockquote: ({ node: _node, ...props }) => (
            <blockquote className="mb-2 border-l-2 border-gray-700 pl-3 text-gray-400" {...props} />
          ),
          hr: ({ node: _node, ...props }) => <hr className="my-4 border-gray-800" {...props} />,
          table: ({ node: _node, ...props }) => (
            <div className="mb-2 min-w-0 max-w-full overflow-x-auto">
              <table className="w-full min-w-[480px] border-collapse text-xs [overflow-wrap:normal]" {...props} />
            </div>
          ),
          th: ({ node: _node, ...props }) => (
            <th className="border-b border-gray-700 px-2 py-1.5 text-left font-semibold text-gray-300" {...props} />
          ),
          td: ({ node: _node, ...props }) => (
            <td className="border-b border-gray-800/60 px-2 py-1.5 align-top text-gray-400" {...props} />
          ),
};

/**
 * Memorando de la tesis renderizado como markdown formateado (antes se
 * pintaba el texto crudo con pipes y almohadillas en un <pre>). Solo
 * markdown seguro: react-markdown no ejecuta HTML en crudo. Las tablas
 * GFM se envuelven para scroll horizontal en móvil.
 */
export default function ThesisMarkdown({ content }: { content: string }) {
  return (
    <div className="min-w-0 max-w-full [overflow-wrap:anywhere] rounded-lg border border-gray-800 bg-black/20 p-4 text-sm leading-6 text-gray-300">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        ...markdownComponents,
        a: ({ node: _node, children, ...props }) => (
          <a className="break-words text-teal-400 underline" target="_blank" rel="noopener noreferrer" {...props}>
            {typeof children === 'string' && /^https?:\/\//.test(children) ? 'Fuente' : children}
          </a>
        ),
        code: ({ node: _node, className, children, ...props }) => (
          <code className={`rounded bg-gray-800 px-1 py-0.5 font-mono text-[0.85em] text-gray-200 ${className ?? ''}`} {...props}>
            {!className && typeof children === 'string' ? thesisCodeLabel(children) : children}
          </code>
        ),
      }}>
        {cleanThesisMarkdown(content)}
      </ReactMarkdown>
    </div>
  );
}
