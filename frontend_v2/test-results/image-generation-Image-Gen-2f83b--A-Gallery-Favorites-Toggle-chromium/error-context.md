# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: image-generation.spec.js >> Image Generation & Asset Management (Module A) >> Gallery Favorites Toggle
- Location: e2e/image-generation.spec.js:80:3

# Error details

```
Error: Channel closed
```

```
Error: locator.click: Target page, context or browser has been closed
Call log:
  - waiting for getByRole('button', { name: /favorite|star|unfavorite/i }).first()
    - locator resolved to <button type="button" title="Show Favorites Only" class="flex items-center gap-2 px-3 py-2 rounded-lg transition-colors text-sm bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-yellow-400 border border-gray-700">…</button>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
    - retrying click action
    - waiting 20ms
    - waiting for element to be visible, enabled and stable
    - element is visible, enabled and stable
    - scrolling into view if needed
    - done scrolling
    - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  2 × retrying click action
      - waiting 100ms
      - waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  12 × retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  2 × retrying click action
      - waiting 500ms
      - waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  - retrying click action
    - waiting 500ms
    - waiting for element to be visible, enabled and stable
    - element is not stable
  - retrying click action
    - waiting 500ms
    - waiting for element to be visible, enabled and stable
    - element is visible, enabled and stable
    - scrolling into view if needed
    - done scrolling
    - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  2 × retrying click action
      - waiting 500ms
      - waiting for element to be visible, enabled and stable
      - element is not stable
  3 × retrying click action
      - waiting 500ms
      - waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
    - retrying click action
      - waiting 500ms
      - waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
    - retrying click action
      - waiting 500ms
      - waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
    - retrying click action
      - waiting 500ms
      - waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  - retrying click action
    - waiting 500ms
    - waiting for element to be visible, enabled and stable
    - element is visible, enabled and stable
    - scrolling into view if needed
    - done scrolling
    - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  - retrying click action
    - waiting 500ms
    - waiting for element to be visible, enabled and stable
    - element is not stable
  13 × retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  - retrying click action
    - waiting 500ms
    - waiting for element to be visible, enabled and stable
    - element is visible, enabled and stable
    - scrolling into view if needed
    - done scrolling
    - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  - retrying click action
    - waiting 500ms
    - waiting for element to be visible, enabled and stable
    - element is not stable
  34 × retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <div class="flex-1 flex flex-col items-center justify-center p-2 overflow-hidden bg-black relative">…</div> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
     - retrying click action
       - waiting 500ms
       - waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <img loading="lazy" alt="AgenticGen_00010_.png" src="/api/view/output/AgenticGen_00010_.png" class="↵                        transition-opacity duration-500↵                        opacity-100↵                        max-w-full max-h-full object-contain↵                    "/> from <div class="fixed inset-0 z-50 bg-black/95 flex items-center justify-center p-4">…</div> subtree intercepts pointer events
  - retrying click action
    - waiting 500ms

```

# Test source

```ts
  1   | import { test, expect } from '@playwright/test';
  2   | import { API_BASE, apiDelete, apiGet, apiPost, closeModal, waitForToast } from './fixtures.js';
  3   | 
  4   | test.describe('Image Generation & Asset Management (Module A)', () => {
  5   |   test.setTimeout(180000);
  6   | 
  7   |   test.afterEach(async ({ page }) => {
  8   |     try {
  9   |       await apiDelete(page, '/jobs');
  10  |     } catch {
  11  |       // best-effort cleanup
  12  |     }
  13  |   });
  14  | 
  15  |   test('Full Text2Img with Custom Parameters', async ({ page }) => {
  16  |     await page.goto('/generate');
  17  | 
  18  |     const prompt = page.getByPlaceholder('Describe what you want to create...');
  19  |     await prompt.fill('A red apple in a basket, photorealistic, studio lighting');
  20  | 
  21  |     const negativePrompt = page.getByPlaceholder('Negative prompt...');
  22  |     await negativePrompt.fill('blurry, low quality');
  23  | 
  24  |     const stepsInput = page.locator('input[type="number"]').first();
  25  |     if (await stepsInput.isVisible()) {
  26  |       await stepsInput.fill('30');
  27  |     }
  28  | 
  29  |     const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
  30  |     await expect(generateBtn).toBeEnabled();
  31  |     await closeModal(page);
  32  |     await generateBtn.click({ force: true });
  33  | 
  34  |     await page.waitForURL('**/', { timeout: 30000 });
  35  | 
  36  |     await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
  37  |   });
  38  | 
  39  |   test('Img2Img Upload and Generate', async ({ page }) => {
  40  |     await page.goto('/img2img');
  41  | 
  42  |     const prompt = page.getByPlaceholder('Describe what you want to create...');
  43  |     await prompt.fill('oil painting style');
  44  | 
  45  |     const fileInput = page.locator('input[type="file"]').first();
  46  |     await fileInput.setInputFiles({
  47  |       name: 'test.png',
  48  |       mimeType: 'image/png',
  49  |       buffer: Buffer.from(
  50  |         '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="100%" height="100%" fill="#808080"/></svg>'
  51  |       ),
  52  |     });
  53  | 
  54  |     await page.waitForTimeout(1000);
  55  | 
  56  |     const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
  57  |     if (await generateBtn.isVisible()) {
  58  |       await closeModal(page);
  59  |       await generateBtn.click({ force: true });
  60  |       await page.waitForURL('**/', { timeout: 30000 });
  61  |       await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
  62  |     }
  63  |   });
  64  | 
  65  |   test('Inpaint Mask Canvas', async ({ page }) => {
  66  |     await page.goto('/inpaint');
  67  | 
  68  |     const prompt = page.getByPlaceholder('Describe what you want to create...');
  69  |     await prompt.fill('a cat sitting here');
  70  | 
  71  |     const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
  72  |     if (await generateBtn.isVisible()) {
  73  |       await closeModal(page);
  74  |       await generateBtn.click({ force: true });
  75  |       await page.waitForURL('**/', { timeout: 30000 });
  76  |       await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
  77  |     }
  78  |   });
  79  | 
  80  |   test('Gallery Favorites Toggle', async ({ page }) => {
  81  |     await page.goto('/');
  82  |     await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });
  83  | 
  84  |     const firstImage = page.locator('img:not([alt="Logo"])').first();
  85  |     await expect(firstImage).toBeVisible({ timeout: 60000 });
  86  |     await firstImage.click({ force: true });
  87  | 
  88  |     const favoriteBtn = page.getByRole('button', { name: /favorite|star|unfavorite/i }).first();
  89  |     if (await favoriteBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
> 90  |       await favoriteBtn.click();
      |                         ^ Error: locator.click: Target page, context or browser has been closed
  91  |       await waitForToast(page, /favorite/i, 5000);
  92  |     }
  93  | 
  94  |     await page.keyboard.press('Escape');
  95  |   });
  96  | 
  97  |   test('Pull to Refresh', async ({ page }) => {
  98  |     await page.goto('/');
  99  |     await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });
  100 | 
  101 |     const gallery = page.locator('.max-w-7xl').first();
  102 |     await gallery.dispatchEvent('touchstart', { touchPoints: [{ clientY: 200 }] });
  103 |     await gallery.dispatchEvent('touchmove', { touchPoints: [{ clientY: 100 }] });
  104 |     await gallery.dispatchEvent('touchend');
  105 | 
  106 |     await page.waitForTimeout(2000);
  107 |   });
  108 | 
  109 |   test('Batch Actions: Select and Favorite', async ({ page }) => {
  110 |     await page.goto('/');
  111 |     await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });
  112 | 
  113 |     await page.keyboard.press('s');
  114 | 
  115 |     const images = page.locator('img:not([alt="Logo"])');
  116 |     const count = await images.count();
  117 |     if (count >= 2) {
  118 |       await images.nth(0).click({ force: true });
  119 |       await images.nth(1).click({ force: true });
  120 | 
  121 |       const favBtn = page.getByRole('button', { name: /favorite|star/i });
  122 |       if (await favBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
  123 |         await favBtn.click();
  124 |         await waitForToast(page, /favorit/i, 8000);
  125 |       }
  126 |     }
  127 |   });
  128 | 
  129 |   test('Lightbox Navigation and Reuse Parameters', async ({ page }) => {
  130 |     await page.goto('/');
  131 |     await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });
  132 | 
  133 |     const firstImage = page.locator('img:not([alt="Logo"])').first();
  134 |     await firstImage.click({ force: true });
  135 | 
  136 |     const nextBtn = page.getByRole('button', { name: /next|arrow|›/i }).first();
  137 |     if (await nextBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
  138 |       await nextBtn.click();
  139 |       await page.waitForTimeout(500);
  140 |     }
  141 | 
  142 |     const reuseBtn = page.getByRole('button', { name: /reuse parameters/i });
  143 |     if (await reuseBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
  144 |       await reuseBtn.click();
  145 |       await page.waitForURL('**/generate', { timeout: 10000 });
  146 |       const prompt = page.getByPlaceholder('Describe what you want to create...');
  147 |       const value = await prompt.inputValue();
  148 |       expect(value.length).toBeGreaterThan(0);
  149 |     } else {
  150 |       await page.keyboard.press('Escape');
  151 |     }
  152 |   });
  153 | 
  154 |   test('Job History Clear', async ({ page }) => {
  155 |     await page.goto('/');
  156 |     await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });
  157 | 
  158 |     const clearBtn = page.getByRole('button', { name: /clear history/i });
  159 |     if (await clearBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
  160 |       await clearBtn.click();
  161 |       const confirmBtn = page.getByRole('button', { name: /clear/i }).first();
  162 |       if (await confirmBtn.isVisible()) {
  163 |         await confirmBtn.click();
  164 |       }
  165 |       await waitForToast(page, /cleared|removed/i, 5000);
  166 |     }
  167 |   });
  168 | 
  169 |   test('Advanced Workflow JSON Submit', async ({ page }) => {
  170 |     await page.goto('/advanced');
  171 | 
  172 |     const promptInput = page.getByPlaceholder(/prompt|positive/i).first();
  173 |     if (await promptInput.isVisible()) {
  174 |       await promptInput.fill('a mountain landscape');
  175 |     }
  176 | 
  177 |     const submitBtn = page.getByRole('button', { name: /submit|generate|queue/i }).first();
  178 |     if (await submitBtn.isVisible()) {
  179 |       await submitBtn.click();
  180 |       await page.waitForURL('**/', { timeout: 30000 });
  181 |       await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
  182 |     }
  183 |   });
  184 | 
  185 |   test('Collection Creation from Selection', async ({ page }) => {
  186 |     await page.goto('/');
  187 |     await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });
  188 | 
  189 |     await page.keyboard.press('s');
  190 | 
```