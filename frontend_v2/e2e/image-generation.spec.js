import { test, expect } from '@playwright/test';

test.describe('Image Generation (Module A)', () => {
  test('Simple Text2Img & Gallery Flow', async ({ page }) => {
    // 1. Navigate directly to /generate
    await page.goto('/generate');
    
    // 2. Fill in the Prompt textarea
    const promptTextarea = page.getByPlaceholder('Describe what you want to create...');
    await promptTextarea.fill('A red apple in a basket, photorealistic');

    // 3. Click the "Generate" button
    const generateBtn = page.getByRole('button', { name: 'Generate', exact: true });
    await expect(generateBtn).toBeVisible();
    await expect(generateBtn).toBeEnabled();
    
    // We can also click it directly.
    await generateBtn.click();

    // 4. Assert: UI redirects to '/' and image appears in the gallery
    await page.waitForURL('**/');

    // Wait for the new image to render in the gallery.
    // The gallery images are usually rendered as <img> tags.
    // We wait for at least one image to be visible.
    // Since this is an E2E test, we should give it a generous timeout (60 seconds)
    // for the backend and provider to generate the image.
    await expect(page.locator('img').first()).toBeVisible({ timeout: 60000 });
  });
});
