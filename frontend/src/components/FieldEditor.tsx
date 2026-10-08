import type { CustomField, User } from '../api/client';
import { Input, Select } from './ui';

interface Props {
  field: CustomField;
  value: unknown;
  users: User[];
  onChange: (value: unknown) => void;
}

/** Editor for one custom field value; emits null to clear. */
export function FieldEditor({ field, value, users, onChange }: Props) {
  const id = `cf-${field.id}`;
  switch (field.type) {
    case 'select':
      return (
        <Select id={id} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">—</option>
          {field.options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.label}
            </option>
          ))}
        </Select>
      );
    case 'multi_select': {
      const selected = new Set((value as string[]) ?? []);
      return (
        <fieldset id={id} className="flex flex-wrap gap-2" aria-label={field.name}>
          {field.options.map((o) => (
            <label key={o.id} className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                checked={selected.has(o.id)}
                onChange={(e) => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(o.id);
                  else next.delete(o.id);
                  onChange(next.size ? [...next] : null);
                }}
              />
              {o.label}
            </label>
          ))}
        </fieldset>
      );
    }
    case 'user':
      return (
        <Select id={id} value={(value as string) ?? ''} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">—</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </Select>
      );
    case 'checkbox':
      return <input id={id} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />;
    case 'number':
      return (
        <Input
          id={id}
          type="number"
          defaultValue={(value as number | undefined) ?? ''}
          onBlur={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        />
      );
    case 'date':
      return (
        <Input
          id={id}
          type="date"
          defaultValue={(value as string | undefined) ?? ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
    default:
      return (
        <Input
          id={id}
          type={field.type === 'url' ? 'url' : 'text'}
          defaultValue={(value as string | undefined) ?? ''}
          onBlur={(e) => onChange(e.target.value || null)}
        />
      );
  }
}
