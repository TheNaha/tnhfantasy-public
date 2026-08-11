import { test, expect } from '@playwright/test';

const API_BASE = '/api';

async function apiDelete(page, path) {
  const res = await page.request.delete(API_BASE + path);
  if (!res.ok()) throw new Error(`Cleanup DELETE ${path} failed: ${res.status()}`);
}

async function apiGet(page, path) {
  const res = await page.request.get(API_BASE + path);
  if (!res.ok()) throw new Error(`GET ${path} failed: ${res.status()}`);
  return res.json();
}

async function apiPost(page, path, body) {
  const res = await page.request.post(API_BASE + path, {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok()) throw new Error(`POST ${path} failed: ${res.status()}`);
  return res.json();
}

async function apiPut(page, path, body) {
  const res = await page.request.put(API_BASE + path, {
    data: body,
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok()) throw new Error(`PUT ${path} failed: ${res.status()}`);
  return res.json();
}

async function waitForToast(page, regex, timeout = 10000) {
  const selectors = [
    '[class*="toast"]',
    '[class*="Toast"]',
    '[role="status"]',
    '[aria-live="polite"]',
    '.react-hot-toast',
  ];

  for (const sel of selectors) {
    const toast = page.locator(sel).last();
    try {
      await expect(toast).toContainText(regex, { timeout: 2000 });
      return;
    } catch {
      // try next selector
    }
  }

  await page.waitForTimeout(Math.min(timeout, 3000));
}

async function waitForStreamingToFinish(page, timeout = 120000) {
  const stopBtn = page.getByRole('button', { name: /stop generating|stop/i }).first();
  if (await stopBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
    await stopBtn.click();
    await page.waitForTimeout(1000);
  }
  await page.waitForTimeout(2000);
}

async function closeModal(page) {
  const modal = page.locator('[role="dialog"], [class*="modal"]').first();
  if (await modal.isVisible({ timeout: 1000 }).catch(() => false)) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
  }
}

export {
  API_BASE,
  apiDelete,
  apiGet,
  apiPost,
  apiPut,
  waitForToast,
  waitForStreamingToFinish,
  closeModal,
};
