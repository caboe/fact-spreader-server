/** Runtime light/dark override on top of the CSS prefers-color-scheme default. */
export type Theme = 'auto' | 'light' | 'dark';

const STORAGE_KEY = 'fs-theme';

export function initialTheme(): Theme {
  if (typeof localStorage === 'undefined') return 'auto';
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'light' || stored === 'dark' ? stored : 'auto';
}

export function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (theme === 'auto') {
    delete root.dataset.theme;
  } else {
    root.dataset.theme = theme;
  }
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, theme);
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (meta) {
    const dark =
      theme === 'dark' ||
      (theme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    meta.content = dark ? '#0b1220' : '#f8fafc';
  }
}
