import { useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';

import type { User } from '../api/client';
import { Button } from './ui';

/** Textarea with @mention suggestions; mentions are inserted as @[Name](user:<id>) tokens. */
export function CommentComposer({
  users,
  busy,
  onSubmit,
}: {
  users: User[];
  busy: boolean;
  onSubmit: (body: string) => void;
}) {
  const [body, setBody] = useState('');
  const [query, setQuery] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  // Caret to restore right after a mention is inserted (synchronously, so fast typing can't race it).
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (pendingCaret.current === null || !ref.current) return;
    ref.current.focus();
    ref.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
    pendingCaret.current = null;
  }, [body]);

  const matches =
    query === null
      ? []
      : users
          .filter((u) => u.name.toLowerCase().includes(query) || u.email.toLowerCase().includes(query))
          .slice(0, 6);

  const update = (text: string, caret: number) => {
    setBody(text);
    const m = /(^|\s)@([\w.-]{0,30})$/.exec(text.slice(0, caret));
    setQuery(m ? m[2]!.toLowerCase() : null);
    setActive(0);
  };

  const insert = (user: User) => {
    const el = ref.current!;
    const caret = el.selectionStart;
    const before = body.slice(0, caret).replace(/@[\w.-]*$/, `@[${user.name}](user:${user.id}) `);
    const next = before + body.slice(caret);
    pendingCaret.current = before.length;
    setBody(next);
    setQuery(null);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (matches.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : matches.length - 1)) % matches.length);
    } else if (matches.length && (e.key === 'Enter' || e.key === 'Tab')) {
      e.preventDefault();
      insert(matches[active]!);
    } else if (e.key === 'Escape' && query !== null) {
      e.stopPropagation();
      setQuery(null);
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && body.trim()) {
      onSubmit(body);
      setBody('');
    }
  };

  return (
    <form
      className="relative flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (body.trim()) {
          onSubmit(body);
          setBody('');
        }
      }}
    >
      <label htmlFor="comment-body" className="sr-only">
        Add a comment
      </label>
      <textarea
        id="comment-body"
        ref={ref}
        rows={3}
        value={body}
        placeholder="Write a comment… use @ to mention (Ctrl+Enter to send)"
        aria-autocomplete="list"
        aria-controls={matches.length ? 'mention-list' : undefined}
        aria-expanded={matches.length > 0}
        role="combobox"
        onKeyDown={onKeyDown}
        onChange={(e) => update(e.target.value, e.target.selectionStart)}
        className="rounded-md border border-slate-300 bg-white p-2 text-sm dark:border-slate-600 dark:bg-slate-900"
      />
      {matches.length > 0 && (
        <ul
          id="mention-list"
          role="listbox"
          className="absolute top-full z-20 mt-1 w-64 rounded-md border border-slate-200 bg-white shadow dark:border-slate-700 dark:bg-slate-900"
        >
          {matches.map((u, i) => (
            <li
              key={u.id}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                insert(u);
              }}
              className={`cursor-pointer px-3 py-1.5 text-sm ${i === active ? 'bg-sky-100 dark:bg-sky-900' : ''}`}
            >
              {u.name} <span className="text-xs text-slate-500">{u.email}</span>
            </li>
          ))}
        </ul>
      )}
      <Button type="submit" disabled={busy || !body.trim()} className="self-end">
        Comment
      </Button>
    </form>
  );
}
