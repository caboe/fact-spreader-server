import type { Page } from '@playwright/test';
import { expect } from '@playwright/test';
import { totp } from './totp';

export const email = process.env.FS_E2E_EMAIL ?? '';
export const password = process.env.FS_E2E_PASSWORD ?? '';
export const secret = process.env.FS_E2E_TOTP_SECRET ?? '';

export const hasCredentials = Boolean(email && password);

export async function signIn(page: Page): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  if (secret) {
    await page.getByLabel(/TOTP/).fill(totp(secret));
  }
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Check a claim' })).toBeVisible();
}


export async function capture(page: Page, name: string): Promise<void> {
  const base = '../docs/screenshots/phase-7';
  const variants: { suffix: string; width: number; height: number; dark: boolean }[] = [
    { suffix: 'light', width: 1280, height: 900, dark: false },
    { suffix: 'dark', width: 1280, height: 900, dark: true },
    { suffix: 'narrow', width: 360, height: 800, dark: false },
    { suffix: 'wide', width: 1440, height: 900, dark: false },
  ];
  for (const variant of variants) {
    await page.setViewportSize({ width: variant.width, height: variant.height });
    await page.emulateMedia({ colorScheme: variant.dark ? 'dark' : 'light' });
    await page.screenshot({ path: `${base}/${name}-${variant.suffix}.png`, fullPage: true });
  }
}
