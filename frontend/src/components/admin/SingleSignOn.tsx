import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, unwrap, type Schemas } from '../../api/client';
import { Button, ErrorText, Field, GhostButton, Input, Select } from '../ui';
import { Copyable, Section } from './common';

type Provider = Schemas['ProviderRead'];

const EMPTY = {
  kind: 'oidc' as 'oidc' | 'saml',
  name: '',
  slug: '',
  issuer: '',
  client_id: '',
  client_secret: '',
  idp_entity_id: '',
  sso_url: '',
  idp_certificate: '',
  email_attribute: '',
  domains: '',
  default_role: 'member' as 'member' | 'guest' | 'admin',
};

function ProviderCard({ p }: { p: Provider }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['sso-providers'] });
  const update = useMutation({
    mutationFn: (body: Schemas['ProviderUpdate']) =>
      unwrap(
        api.PATCH('/api/v1/admin/sso-providers/{provider_id}', {
          params: { path: { provider_id: p.id } },
          body,
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        api.DELETE('/api/v1/admin/sso-providers/{provider_id}', { params: { path: { provider_id: p.id } } }),
      ),
    onSuccess: refresh,
  });
  return (
    <li className="flex flex-col gap-2 rounded border border-slate-200 p-3 dark:border-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">
          {p.name} <span className="text-xs text-slate-500 dark:text-slate-400 uppercase">{p.kind}</span>
          {!p.enabled && <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">(disabled)</span>}
          {p.enforce && (
            <span className="ml-2 text-xs text-amber-700 dark:text-amber-400">required for sign-in</span>
          )}
        </p>
        <div className="flex flex-wrap gap-1">
          <GhostButton onClick={() => update.mutate({ enabled: !p.enabled })}>
            {p.enabled ? 'Disable' : 'Enable'}
          </GhostButton>
          <GhostButton onClick={() => update.mutate({ enforce: !p.enforce })}>
            {p.enforce ? 'Allow passwords' : 'Require SSO'}
          </GhostButton>
          <GhostButton
            aria-label={`Remove ${p.name}`}
            onClick={() => window.confirm(`Remove ${p.name}? People keep their accounts.`) && remove.mutate()}
          >
            Remove
          </GhostButton>
        </div>
      </div>
      <dl className="grid gap-1 text-sm sm:grid-cols-[12rem_1fr]">
        {p.redirect_uri && (
          <>
            <dt className="text-slate-600 dark:text-slate-400">Redirect URI</dt>
            <dd>
              <Copyable value={p.redirect_uri} />
            </dd>
          </>
        )}
        {p.sp_entity_id && (
          <>
            <dt className="text-slate-600 dark:text-slate-400">SP entity ID / metadata</dt>
            <dd>
              <Copyable value={p.sp_entity_id} />
            </dd>
            <dt className="text-slate-600 dark:text-slate-400">ACS URL</dt>
            <dd>
              <Copyable value={p.acs_url ?? ''} />
            </dd>
          </>
        )}
        <dt className="text-slate-600 dark:text-slate-400">Allowed domains</dt>
        <dd>{p.allowed_domains.length ? p.allowed_domains.join(', ') : 'any'}</dd>
        <dt className="text-slate-600 dark:text-slate-400">New accounts</dt>
        <dd>
          {p.jit_provisioning ? `created on first sign-in as ${p.default_role}` : 'must be invited first'}
        </dd>
      </dl>
      <ErrorText error={update.error ?? remove.error} />
    </li>
  );
}

export function SingleSignOn() {
  const queryClient = useQueryClient();
  const [d, setD] = useState(EMPTY);
  const providers = useQuery({
    queryKey: ['sso-providers'],
    queryFn: () => unwrap(api.GET('/api/v1/admin/sso-providers')),
  });
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST('/api/v1/admin/sso-providers', {
          body: {
            kind: d.kind,
            name: d.name,
            slug: d.slug,
            default_role: d.default_role,
            allowed_domains: d.domains
              .split(',')
              .map((x) => x.trim())
              .filter(Boolean),
            ...(d.kind === 'oidc'
              ? { oidc: { issuer: d.issuer, client_id: d.client_id }, client_secret: d.client_secret || null }
              : {
                  saml: {
                    idp_entity_id: d.idp_entity_id,
                    sso_url: d.sso_url,
                    idp_certificate: d.idp_certificate,
                    email_attribute: d.email_attribute || null,
                  },
                }),
          },
        }),
      ),
    onSuccess: async () => {
      setD(EMPTY);
      await queryClient.invalidateQueries({ queryKey: ['sso-providers'] });
    },
  });
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) =>
    setD({ ...d, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <div className="flex flex-col gap-8">
      <Section
        title="Identity providers"
        intro="People sign in with your identity provider (Entra ID, Okta, Google, Authentik, Keycloak…). Requiring SSO turns off password sign-in for everyone except owners, who keep it as break-glass access."
      >
        <ErrorText error={providers.error} />
        {providers.data?.length === 0 && (
          <p className="text-sm text-slate-600 dark:text-slate-400">None yet.</p>
        )}
        <ul className="flex flex-col gap-3">
          {(providers.data ?? []).map((p) => (
            <ProviderCard key={p.id} p={p} />
          ))}
        </ul>
      </Section>
      <Section title="Add a provider">
        <form onSubmit={submit} className="grid max-w-3xl gap-3 sm:grid-cols-2">
          <Field label="Protocol" id="sso-kind">
            <Select id="sso-kind" value={d.kind} onChange={set('kind')}>
              <option value="oidc">OpenID Connect</option>
              <option value="saml">SAML 2.0</option>
            </Select>
          </Field>
          <Field label="Button label" id="sso-name">
            <Input id="sso-name" required value={d.name} onChange={set('name')} placeholder="Company login" />
          </Field>
          <Field label="Short name (in URLs)" id="sso-slug">
            <Input
              id="sso-slug"
              required
              pattern="[a-z0-9-]+"
              value={d.slug}
              onChange={set('slug')}
              placeholder="company"
            />
          </Field>
          <Field label="Allowed email domains (comma-separated)" id="sso-domains">
            <Input id="sso-domains" value={d.domains} onChange={set('domains')} placeholder="example.com" />
          </Field>
          <Field label="Role for new accounts" id="sso-role">
            <Select id="sso-role" value={d.default_role} onChange={set('default_role')}>
              <option value="member">member</option>
              <option value="guest">guest</option>
              <option value="admin">admin</option>
            </Select>
          </Field>
          {d.kind === 'oidc' ? (
            <>
              <Field label="Issuer URL" id="sso-issuer">
                <Input id="sso-issuer" type="url" required value={d.issuer} onChange={set('issuer')} />
              </Field>
              <Field label="Client ID" id="sso-client-id">
                <Input id="sso-client-id" required value={d.client_id} onChange={set('client_id')} />
              </Field>
              <Field label="Client secret" id="sso-client-secret">
                <Input
                  id="sso-client-secret"
                  type="password"
                  autoComplete="off"
                  value={d.client_secret}
                  onChange={set('client_secret')}
                />
              </Field>
            </>
          ) : (
            <>
              <Field label="IdP entity ID" id="sso-entity">
                <Input id="sso-entity" required value={d.idp_entity_id} onChange={set('idp_entity_id')} />
              </Field>
              <Field label="IdP SSO URL (redirect binding)" id="sso-url">
                <Input id="sso-url" type="url" required value={d.sso_url} onChange={set('sso_url')} />
              </Field>
              <Field label="Email attribute (empty: NameID)" id="sso-email-attr">
                <Input id="sso-email-attr" value={d.email_attribute} onChange={set('email_attribute')} />
              </Field>
              <div className="sm:col-span-2">
                <Field label="IdP signing certificate (PEM)" id="sso-cert">
                  <textarea
                    id="sso-cert"
                    required
                    rows={5}
                    value={d.idp_certificate}
                    onChange={set('idp_certificate')}
                    className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-mono text-xs dark:border-slate-600 dark:bg-slate-900"
                  />
                </Field>
              </div>
            </>
          )}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={create.isPending}>
              Add provider
            </Button>
          </div>
        </form>
        <ErrorText error={create.error} />
      </Section>
    </div>
  );
}
