# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: world-vault.spec.js >> World Vault & Lorebooks (Module D) >> Create Lorebook via API and Verify in Chat Context
- Location: e2e/world-vault.spec.js:21:3

# Error details

```
TypeError: Cannot read properties of undefined (reading 'post')
```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | const API_BASE = '/api';
  4  | 
  5  | async function apiDelete(page, path) {
  6  |   const res = await page.request.delete(API_BASE + path);
  7  |   if (!res.ok()) throw new Error(`Cleanup DELETE ${path} failed: ${res.status()}`);
  8  | }
  9  | 
  10 | async function apiGet(page, path) {
  11 |   const res = await page.request.get(API_BASE + path);
  12 |   if (!res.ok()) throw new Error(`GET ${path} failed: ${res.status()}`);
  13 |   return res.json();
  14 | }
  15 | 
  16 | async function apiPost(page, path, body) {
> 17 |   const res = await page.request.post(API_BASE + path, {
     |                                  ^ TypeError: Cannot read properties of undefined (reading 'post')
  18 |     data: body,
  19 |     headers: { 'Content-Type': 'application/json' },
  20 |   });
  21 |   if (!res.ok()) throw new Error(`POST ${path} failed: ${res.status()}`);
  22 |   return res.json();
  23 | }
  24 | 
  25 | async function apiPut(page, path, body) {
  26 |   const res = await page.request.put(API_BASE + path, {
  27 |     data: body,
  28 |     headers: { 'Content-Type': 'application/json' },
  29 |   });
  30 |   if (!res.ok()) throw new Error(`PUT ${path} failed: ${res.status()}`);
  31 |   return res.json();
  32 | }
  33 | 
  34 | async function waitForToast(page, regex, timeout = 10000) {
  35 |   const selectors = [
  36 |     '[class*="toast"]',
  37 |     '[class*="Toast"]',
  38 |     '[role="status"]',
  39 |     '[aria-live="polite"]',
  40 |     '.react-hot-toast',
  41 |   ];
  42 | 
  43 |   for (const sel of selectors) {
  44 |     const toast = page.locator(sel).last();
  45 |     try {
  46 |       await expect(toast).toContainText(regex, { timeout: 2000 });
  47 |       return;
  48 |     } catch {
  49 |       // try next selector
  50 |     }
  51 |   }
  52 | 
  53 |   await page.waitForTimeout(Math.min(timeout, 3000));
  54 | }
  55 | 
  56 | async function waitForStreamingToFinish(page, timeout = 120000) {
  57 |   const stopBtn = page.getByRole('button', { name: /stop generating|stop/i }).first();
  58 |   if (await stopBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
  59 |     await stopBtn.click();
  60 |     await page.waitForTimeout(1000);
  61 |   }
  62 |   await page.waitForTimeout(2000);
  63 | }
  64 | 
  65 | async function closeModal(page) {
  66 |   const modal = page.locator('[role="dialog"], [class*="modal"]').first();
  67 |   if (await modal.isVisible({ timeout: 1000 }).catch(() => false)) {
  68 |     await page.keyboard.press('Escape');
  69 |     await page.waitForTimeout(300);
  70 |   }
  71 | }
  72 | 
  73 | export {
  74 |   API_BASE,
  75 |   apiDelete,
  76 |   apiGet,
  77 |   apiPost,
  78 |   apiPut,
  79 |   waitForToast,
  80 |   waitForStreamingToFinish,
  81 |   closeModal,
  82 | };
  83 | 
```