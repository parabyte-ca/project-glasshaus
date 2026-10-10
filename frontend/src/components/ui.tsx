import {
  cloneElement,
  isValidElement,
  useState,
  type ComponentProps,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react';

import { Link, type LinkProps } from 'react-router';

import { isSaneDate } from '../lib/dates';
import { toast } from '../lib/toast';

const focus = 'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600';
/** Text link style, readable in both themes. */
export const linkClass = 'text-sky-700 underline-offset-2 hover:underline dark:text-sky-400';

export function TextLink({ className = '', ...props }: LinkProps) {
  return <Link className={`${linkClass} ${focus} rounded-sm ${className}`} {...props} />;
}

const field =
  'rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm dark:border-slate-600 dark:bg-slate-900 ' +
  focus;

export function Button({
  className = '',
  danger = false,
  ...props
}: ComponentProps<'button'> & { danger?: boolean }) {
  const tone = danger ? 'bg-red-700 hover:bg-red-800' : 'bg-sky-700 hover:bg-sky-800';
  return (
    <button
      type="button"
      className={`min-h-11 rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 md:min-h-0 ${tone} ${focus} ${className}`}
      {...props}
    />
  );
}

export function GhostButton({ className = '', ...props }: ComponentProps<'button'>) {
  return (
    <button
      type="button"
      className={`min-h-11 rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 md:min-h-0 dark:border-slate-600 dark:hover:bg-slate-800 ${focus} ${className}`}
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

/**
 * A labelled form control. With `error` (see fieldError) the control is marked invalid and points at
 * the message, so screen readers read it with the field.
 */
export function Field({
  label,
  id,
  error,
  children,
}: {
  label: string;
  id: string;
  error?: string;
  children: ReactNode;
}) {
  const errorId = `${id}-error`;
  const control =
    error && isValidElement<{ 'aria-invalid'?: boolean; 'aria-describedby'?: string }>(children)
      ? cloneElement(children, { 'aria-invalid': true, 'aria-describedby': errorId })
      : children;
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {control}
      {error && (
        <p id={errorId} className="text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

/** Copies a value (a token, a link) to the clipboard and says so. */
export function CopyButton({
  value,
  label = 'Copy',
  'aria-label': ariaLabel,
}: {
  value: string;
  label?: string;
  'aria-label'?: string;
}) {
  const [copied, setCopied] = useState(false);
  return (
    <GhostButton
      aria-label={ariaLabel}
      className="shrink-0 px-2 py-1 text-xs"
      onClick={() => {
        void navigator.clipboard
          ?.writeText(value)
          .then(() => {
            setCopied(true);
            toast('Copied to the clipboard');
            setTimeout(() => setCopied(false), 2000);
          })
          .catch(() => toast('Could not copy; select the text and copy it instead', 'error'));
      }}
    >
      {copied ? 'Copied' : label}
    </GhostButton>
  );
}

/**
 * Tabs with the keyboard behaviour people expect: one tab stop, arrow keys (and Home/End) move
 * between tabs and select them. Pair with TabPanel using the same idBase.
 */
export function Tabs<T extends string>({
  label,
  idBase,
  tabs,
  selected,
  onSelect,
  variant = 'underline',
}: {
  label: string;
  idBase: string;
  tabs: readonly (readonly [T, string])[];
  selected: T;
  onSelect: (id: T) => void;
  variant?: 'underline' | 'pill';
}) {
  const move = (index: number) => {
    const next = tabs[(index + tabs.length) % tabs.length];
    if (!next) return;
    onSelect(next[0]);
    document.getElementById(`${idBase}-tab-${next[0]}`)?.focus();
  };
  const style = (active: boolean) =>
    variant === 'pill'
      ? `rounded-md px-3 py-1.5 text-sm ${active ? 'bg-sky-700 text-white' : 'hover:bg-slate-100 dark:hover:bg-slate-800'}`
      : `-mb-px border-b-2 px-3 py-2 text-sm ${
          active
            ? 'border-sky-700 font-medium text-sky-800 dark:border-sky-400 dark:text-sky-300'
            : 'border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'
        }`;
  return (
    <div
      role="tablist"
      aria-label={label}
      className={
        variant === 'pill'
          ? 'flex flex-wrap gap-1'
          : 'flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-800'
      }
    >
      {tabs.map(([id, text], index) => (
        <button
          key={id}
          id={`${idBase}-tab-${id}`}
          role="tab"
          type="button"
          aria-selected={selected === id}
          aria-controls={`${idBase}-panel`}
          tabIndex={selected === id ? 0 : -1}
          onClick={() => onSelect(id)}
          onKeyDown={(e) => {
            const to = {
              ArrowRight: index + 1,
              ArrowDown: index + 1,
              ArrowLeft: index - 1,
              ArrowUp: index - 1,
              Home: 0,
              End: tabs.length - 1,
            }[e.key];
            if (to === undefined) return;
            e.preventDefault();
            move(to);
          }}
          className={`${style(selected === id)} ${focus}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({
  idBase,
  selected,
  children,
}: {
  idBase: string;
  selected: string;
  children: ReactNode;
}) {
  return (
    <div role="tabpanel" id={`${idBase}-panel`} aria-labelledby={`${idBase}-tab-${selected}`} tabIndex={0}>
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
