import {
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react';

import { isSaneDate } from '../lib/dates';

const focus = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600';
const field =
  'rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900 ' +
  focus;

export function Button({ className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`rounded-md bg-sky-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-50 ${focus} ${className}`}
      {...props}
    />
  );
}

export function GhostButton({ className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800 ${focus} ${className}`}
      {...props}
    />
  );
}

export function Input({ className = '', ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${field} ${className}`} {...props} />;
}

/**
 * Date field that saves when you leave it or press Enter, not on every keystroke (typing a year
 * otherwise saves 0002, 0020, 0202…). Escape puts the saved value back.
 */
export function DateInput({
  value,
  onCommit,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'defaultValue' | 'onChange' | 'type'> & {
  value: string | null | undefined;
  onCommit: (value: string | null) => void;
}) {
  const saved = value ?? '';
  const [text, setText] = useState(saved);
  const [base, setBase] = useState(saved);
  if (saved !== base) {
    // The saved value changed elsewhere (another person, a reschedule): show it.
    setBase(saved);
    setText(saved);
  }
  const invalid = !isSaneDate(text);
  const commit = () => {
    if (text === saved) return;
    if (invalid) {
      setText(saved);
      return;
    }
    onCommit(text || null);
  };
  return (
    <Input
      type="date"
      min="1900-01-01"
      max="2200-12-31"
      aria-invalid={invalid || undefined}
      {...props}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          commit();
        } else if (e.key === 'Escape' && text !== saved) {
          e.stopPropagation();
          setText(saved);
        }
      }}
    />
  );
}

export function Select({ className = '', ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`${field} ${className}`} {...props} />;
}

export function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-red-700 dark:text-red-400">
      {error instanceof Error ? error.message : String(error)}
    </p>
  );
}

/** A horizontally/vertically scrolling area that keyboard users can focus and scroll (WCAG 2.1.1). */
export function ScrollArea({
  label,
  className = 'overflow-x-auto',
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className={`${className} ${focus}`}>
      {children}
    </div>
  );
}
