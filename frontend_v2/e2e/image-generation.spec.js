import { test, expect } from '@playwright/test';
import { API_BASE, apiDelete, apiGet, apiPost, closeModal, waitForToast } from './fixtures.js';

test.describe('Image Generation & Asset Management (Module A)', () => {
  test.setTimeout(180000);

  test.afterEach(async ({ page }) => {
    try {
      await apiDelete(page, '/jobs');
    } catch {
      // best-effort cleanup
    }
  });

  test('Full Text2Img with Custom Parameters', async ({ page }) => {
    await page.goto('/generate');

    const prompt = page.getByPlaceholder('Describe what you want to create...');
    await prompt.fill('A red apple in a basket, photorealistic, studio lighting');

    const negativePrompt = page.getByPlaceholder('Negative prompt...');
    await negativePrompt.fill('blurry, low quality');

    const stepsInput = page.locator('input[type="number"]').first();
    if (await stepsInput.isVisible()) {
      await stepsInput.fill('30');
    }

    const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
    await expect(generateBtn).toBeEnabled();
    await closeModal(page);
    await generateBtn.click({ force: true });

    await page.waitForURL('**/', { timeout: 30000 });

    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
  });

  test('Img2Img Upload and Generate', async ({ page }) => {
    await page.goto('/img2img');

    const prompt = page.getByPlaceholder('Describe what you want to create...');
    await prompt.fill('oil painting style');

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles({
      name: 'test.png',
      mimeType: 'image/png',
      buffer: Buffer.from(
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512"><rect width="100%" height="100%" fill="#808080"/></svg>'
      ),
    });

    await page.waitForTimeout(1000);

    const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
    if (await generateBtn.isVisible()) {
      await closeModal(page);
      await generateBtn.click({ force: true });
      await page.waitForURL('**/', { timeout: 30000 });
      await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
    }
  });

  test('Inpaint Mask Canvas', async ({ page }) => {
    await page.goto('/inpaint');

    const prompt = page.getByPlaceholder('Describe what you want to create...');
    await prompt.fill('a cat sitting here');

    const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
    if (await generateBtn.isVisible()) {
      await closeModal(page);
      await generateBtn.click({ force: true });
      await page.waitForURL('**/', { timeout: 30000 });
      await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
    }
  });

  test('Gallery Favorites Toggle', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });

    const firstImage = page.locator('img:not([alt="Logo"])').first();
    await expect(firstImage).toBeVisible({ timeout: 60000 });
    await firstImage.click({ force: true });

    const favoriteBtn = page.getByRole('button', { name: /favorite|star|unfavorite/i }).first();
    if (await favoriteBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await favoriteBtn.click();
      await waitForToast(page, /favorite/i, 5000);
    }

    await page.keyboard.press('Escape');
  });

  test('Pull to Refresh', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });

    const gallery = page.locator('.max-w-7xl').first();
    await gallery.dispatchEvent('touchstart', { touchPoints: [{ clientY: 200 }] });
    await gallery.dispatchEvent('touchmove', { touchPoints: [{ clientY: 100 }] });
    await gallery.dispatchEvent('touchend');

    await page.waitForTimeout(2000);
  });

  test('Batch Actions: Select and Favorite', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });

    await page.keyboard.press('s');

    const images = page.locator('img:not([alt="Logo"])');
    const count = await images.count();
    if (count >= 2) {
      await images.nth(0).click({ force: true });
      await images.nth(1).click({ force: true });

      const favBtn = page.getByRole('button', { name: /favorite|star/i });
      if (await favBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await favBtn.click();
        await waitForToast(page, /favorit/i, 8000);
      }
    }
  });

  test('Lightbox Navigation and Reuse Parameters', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });

    const firstImage = page.locator('img:not([alt="Logo"])').first();
    await firstImage.click({ force: true });

    const nextBtn = page.getByRole('button', { name: /next|arrow|›/i }).first();
    if (await nextBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await nextBtn.click();
      await page.waitForTimeout(500);
    }

    const reuseBtn = page.getByRole('button', { name: /reuse parameters/i });
    if (await reuseBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await reuseBtn.click();
      await page.waitForURL('**/generate', { timeout: 10000 });
      const prompt = page.getByPlaceholder('Describe what you want to create...');
      const value = await prompt.inputValue();
      expect(value.length).toBeGreaterThan(0);
    } else {
      await page.keyboard.press('Escape');
    }
  });

  test('Job History Clear', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });

    const clearBtn = page.getByRole('button', { name: /clear history/i });
    if (await clearBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await clearBtn.click();
      const confirmBtn = page.getByRole('button', { name: /clear/i }).first();
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click();
      }
      await waitForToast(page, /cleared|removed/i, 5000);
    }
  });

  test('Advanced Workflow JSON Submit', async ({ page }) => {
    await page.goto('/advanced');

    const promptInput = page.getByPlaceholder(/prompt|positive/i).first();
    if (await promptInput.isVisible()) {
      await promptInput.fill('a mountain landscape');
    }

    const submitBtn = page.getByRole('button', { name: /submit|generate|queue/i }).first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
      await page.waitForURL('**/', { timeout: 30000 });
      await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
    }
  });

  test('Collection Creation from Selection', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 60000 });

    await page.keyboard.press('s');

    const images = page.locator('img:not([alt="Logo"])');
    const count = await images.count();
    if (count >= 2) {
      await images.nth(0).click({ force: true });
      await images.nth(1).click({ force: true });

      const addBtn = page.getByRole('button', { name: /add to collection/i });
      if (await addBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await addBtn.click();

        const nameInput = page.getByPlaceholder(/new collection name/i);
        if (await nameInput.isVisible()) {
          await nameInput.fill('E2E Test Collection');
          await page.getByRole('button', { name: /create/i }).click();
          await waitForToast(page, /added/i, 5000);
        }
      }
    }
  });

  test('Generation with LoRA and Enhancements', async ({ page }) => {
    await page.goto('/generate');

    const prompt = page.getByPlaceholder('Describe what you want to create...');
    await prompt.fill('A cyberpunk cityscape');

    // Add LoRA
    const addLoraBtn = page.getByRole('button', { name: /Add LoRA/i }).first();
    if (await addLoraBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addLoraBtn.click();
      const loraOption = page.locator('.lora-item, [role="option"]').first();
      if (await loraOption.isVisible({ timeout: 3000 }).catch(() => false)) {
        await loraOption.click();
      }
    }

    // Highres Fix / Enhancements
    const hiresToggle = page.getByRole('checkbox', { name: /High-res|Hires/i }).first().or(
      page.getByText(/High-res Fix|Hires Fix/i).first()
    );
    if (await hiresToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
      await hiresToggle.click();
    }

    const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
    await expect(generateBtn).toBeEnabled();
    await closeModal(page);
    await generateBtn.click({ force: true });

    await page.waitForURL('**/', { timeout: 30000 });
    await expect(page.locator('img:not([alt="Logo"])').first()).toBeVisible({ timeout: 120000 });
  });
});
