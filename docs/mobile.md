# Phone: My tasks offline and notifications

Glasshaus works as an app on phones and desktops (install it from the browser: **Add to Home Screen**
on iPhone and iPad, **Install app** in Chrome, Edge and Android).

## My tasks

**My tasks** (`/my`, or press **G** then **M**) lists your open tasks in every project, grouped as **Overdue**,
**Today**, **Next 7 days**, **Later** and **No due date**. Tick a task to mark it done; it moves to the
project's first *Done* status.

### Without a connection

- Each time My tasks loads, a copy of the list is kept on the device: key, title, due date, priority
  and status, nothing else. Open My tasks once while online and it opens offline afterwards, with a
  note saying when the copy was made.
- Tasks you tick while offline are kept on the device and marked done as soon as the app can reach the
  server again; the page shows how many are waiting. Ticking a task twice (offline, then again on
  another device) is harmless.
- If a waiting task was deleted or you lost access to it meanwhile, you get a message and it is
  dropped.
- Only My tasks works offline. Other pages show a banner pointing back to it.
- **Sign out** removes the copy, the waiting ticks and the device's notification subscription, so a
  shared device keeps nothing of yours.

API responses are never cached by the service worker; the copy is kept by the app itself in the
browser's storage.

## Notifications on this device

**Account → Notifications on this device → Turn on notifications** sends your Glasshaus notifications
(mentions, assignments, report alerts, backup notices for admins) to this phone or computer, even when
the app is closed. Tapping one opens the right page. **Send a test** checks it works; **Turn off on this
device** stops it. Turn it on separately on each device.

Requirements:

- **HTTPS.** Browsers only allow notifications on an `https://` address (or `localhost`). Put
  Glasshaus behind your reverse proxy with a certificate and set `GLASSHAUS_PUBLIC_URL` to it.
- **iPhone and iPad** (iOS 16.4 or later): add Glasshaus to the Home Screen first, open it from there,
  then turn notifications on. Safari tabs cannot get notifications.
- **Outbound access** from the worker container to the browsers' push services:
  `fcm.googleapis.com` / `android.googleapis.com` (Chrome, Edge on Android, Android),
  `*.push.apple.com` (Safari, iOS), `*.push.services.mozilla.com` (Firefox) and
  `*.notify.windows.com` (Edge on Windows). Subscriptions to any other address are refused.

How it works:

- Notifications are sent with standard Web Push (VAPID, payloads encrypted for the device). The
  signing key is derived from `GLASSHAUS_SECRET_KEY`; nothing extra to configure. Changing the secret
  key means every device has to turn notifications on again.
- The worker checks for new notifications every 10 seconds. Notifications older than 10 minutes are
  not pushed (the moment has passed).
- A device the push service reports as gone, or that fails 20 times in a row, is removed.
- A device belongs to whoever turned notifications on there last.

API: `POST /api/v1/tasks/{ref}/complete` and `/reopen`; `GET /api/v1/push`,
`POST /api/v1/push/subscriptions`, `POST /api/v1/push/subscriptions/remove`, `POST /api/v1/push/test`.
