import ReactMarkdown from 'react-markdown';

/** Render untrusted markdown safely: no raw HTML, mention tokens shown as names, links open safely. */
export function Markdown({ text }: { text: string }) {
  const display = text.replace(/@\[([^\]]+)\]\(user:[0-9a-f-]{36}\)/gi, '**@$1**');
  return (
    <div className="prose-sm max-w-none text-sm leading-relaxed [&_a]:text-sky-700 [&_a]:underline dark:[&_a]:text-sky-400 [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 dark:[&_code]:bg-slate-800 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-1 [&_ul]:list-disc [&_ul]:pl-5">
      <ReactMarkdown
        skipHtml
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer nofollow">
              {children}
            </a>
          ),
        }}
      >
        {display}
      </ReactMarkdown>
    </div>
  );
}
