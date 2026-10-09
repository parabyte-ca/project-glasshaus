# Accessibility

Glasshaus targets **WCAG 2.1 level AA**.

## How it is checked

- **Automated (every CI run):** the Playwright suite in [`e2e/`](../e2e) runs
  [axe-core](https://github.com/dequelabs/axe-core) with the WCAG 2.0/2.1 A and AA rules on every main
  screen — sign-in, home, all five project layouts, the task drawer, report and settings, account, time,
  workload, dashboards, portfolios, goals, every admin tab, the command palette and the shortcut help —
  in both light and dark themes, plus a phone-sized viewport (which also checks nothing scrolls
  sideways). Any violation fails the build.
- **Keyboard tests:** skip link, focus trapped in dialogs and returned on close, shortcuts and the
  palette.
- **Unit tests** use accessible queries (roles and labels), so unlabelled controls fail them.
- **Lint:** `eslint-plugin-jsx-a11y` in `make check`.

Automated tools find roughly a third of issues. Before a release, also check by hand:

- [ ] Every flow with the keyboard only (Tab, Shift+Tab, Enter, Space, arrows, Esc).
- [ ] A screen reader (NVDA + Firefox, or VoiceOver + Safari) on sign-in, creating and editing a task,
      the board, timeline and the command palette.
- [ ] 200 % and 400 % zoom (reflow at 320 CSS px), and Windows high-contrast mode.
- [ ] `prefers-reduced-motion` and dark mode.

## Built in

- Landmarks, a skip link, one `h1` per page and labelled form controls.
- Visible focus indicators; dialogs (task drawer, palette, shortcut help) trap focus and return it.
  Escape closes only the topmost one, and leaving the task drawer saves the field being edited.
- Date fields save when you leave them or press Enter (Escape restores the saved date), so partly
  typed dates are never stored.
- On phones the navigation sits behind a **Menu** button (`aria-expanded`) instead of above every page.
- Board cards move with the keyboard; timeline bars move and resize with arrow keys; charts have data
  tables.
- Scrolling regions (board, table, timeline, wide tables) are focusable so they scroll with the keyboard.
- Colour is never the only signal (status names, severity labels, text with every chart colour); text
  contrast is at least 4.5:1 in both themes.
- Keyboard shortcuts are single keys only outside text fields and can be ignored entirely; everything
  has a visible control too. Press **?** for the list.

## Reporting a problem

Open an issue with the screen, what you expected, and your browser and assistive technology.
