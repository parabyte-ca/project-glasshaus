import { api, unwrap } from '../api/client';

/** Phone and desktop notifications for this device (Web Push through the service worker). */
export type PushState = 'unsupported' | 'needs-install' | 'blocked' | 'off' | 'on';

const isIos = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
const installed = () =>
  window.matchMedia?.('(display-mode: standalone)').matches ||
  (navigator as Navigator & { standalone?: boolean }).standalone === true;

function supported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null;
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return isIos() && !installed() ? 'needs-install' : 'unsupported';
  if (Notification.permission === 'denied') return 'blocked';
  const reg = await registration();
  if (!reg) return 'unsupported';
  return (await reg.pushManager.getSubscription()) ? 'on' : 'off';
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const text = atob(
    base64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (base64url.length % 4)) % 4),
  );
  const bytes = new Uint8Array(new ArrayBuffer(text.length));
  for (let i = 0; i < text.length; i += 1) bytes[i] = text.charCodeAt(i);
  return bytes;
}

function device(): string {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /Firefox\//.test(ua)
      ? 'Firefox'
      : /Chrome\//.test(ua)
        ? 'Chrome'
        : /Safari\//.test(ua)
          ? 'Safari'
          : 'Browser';
  const system = /Android/.test(ua)
    ? 'Android'
    : /iPhone|iPad/.test(ua)
      ? 'iOS'
      : /Mac OS/.test(ua)
        ? 'macOS'
        : /Windows/.test(ua)
          ? 'Windows'
          : 'Linux';
  return `${browser} on ${system}`;
}

export async function turnOn(): Promise<PushState> {
  const reg = await registration();
  if (!reg || !supported()) return 'unsupported';
  if ((await Notification.requestPermission()) !== 'granted') return 'blocked';
  const { public_key } = await unwrap(api.GET('/api/v1/push'));
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) }));
  const json = sub.toJSON();
  await unwrap(
    api.POST('/api/v1/push/subscriptions', {
      body: {
        endpoint: sub.endpoint,
        keys: { p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '' },
        device: device(),
      },
    }),
  );
  return 'on';
}

/** Turn notifications off for this device (also on sign-out, so a shared device stops getting them). */
export async function turnOff(): Promise<PushState> {
  const reg = await registration();
  const sub = reg ? await reg.pushManager.getSubscription() : null;
  if (sub) {
    await api
      .POST('/api/v1/push/subscriptions/remove', { body: { endpoint: sub.endpoint } })
      .catch(() => undefined);
    await sub.unsubscribe().catch(() => false);
  }
  return supported() ? 'off' : 'unsupported';
}
