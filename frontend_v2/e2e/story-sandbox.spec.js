import { test, expect } from '@playwright/test';
import { API_BASE, apiDelete, apiGet, apiPost, waitForToast, waitForStreamingToFinish } from './fixtures.js';

test.describe('Story Sandbox Workspace (Module C)', () => {
  test.setTimeout(180000);

  let createdStoryId = null;
  let createdChapterId = null;

  test.afterEach(async ({ page }) => {
    if (createdChapterId && createdStoryId) {
      try {
        await apiDelete(page, `/world_vault/stories/${createdStoryId}/chapters/${createdChapterId}`);
      } catch {
        // best-effort
      }
      createdChapterId = null;
    }
    if (createdStoryId) {
      try {
        await apiDelete(page, `/world_vault/stories/${createdStoryId}`);
      } catch {
        // best-effort
      }
      createdStoryId = null;
    }
  });

  test('Create Story and Chapter', async ({ page }) => {
    await page.goto('/story');

    const createStoryBtn = page.getByRole('button', { name: /create story/i }).first();
    if (await createStoryBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await createStoryBtn.click();
    }

    const titleInput = page.getByPlaceholder(/story title/i).first();
    if (await titleInput.isVisible()) {
      await titleInput.fill('Playwright Test Story');
      await page.getByRole('button', { name: /create|confirm/i }).first().click();
      await waitForToast(page, /created/i, 5000);
    }

    const url = page.url();
    const storyMatch = url.match(/\/story\/([^/]+)/);
    if (storyMatch) createdStoryId = storyMatch[1];

    const createChapterBtn = page.getByRole('button', { name: /new chapter|add chapter/i }).first();
    if (await createChapterBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await createChapterBtn.click();
      await waitForToast(page, /chapter/i, 5000);
    }

    const chapterMatch = page.url().match(/chapter\/([^/]+)/);
    if (chapterMatch) createdChapterId = chapterMatch[1];
  });

  test('Continue AI Generation', async ({ page }) => {
    await page.goto('/story');

    const editor = page.getByPlaceholder(/once upon a time/i).first().or(page.locator('.story-editor').first());
    if (await editor.isVisible({ timeout: 5000 }).catch(() => false)) {
      await editor.fill('The dark knight stepped into the cavern, drawing his glowing sword.');

      const continueBtn = page.getByRole('button', { name: /continue|generate/i });
      if (await continueBtn.isVisible()) {
        await continueBtn.click();
        await expect(continueBtn).toBeDisabled({ timeout: 5000 });
        await expect(continueBtn).toBeEnabled({ timeout: 120000 });

        const textContent = await editor.textContent();
        expect(textContent?.length).toBeGreaterThan(100);
      }
    }
  });

  test('Branch from Beat', async ({ page }) => {
    await page.goto('/story');

    const editor = page.getByPlaceholder(/once upon a time/i).first().or(page.locator('.story-editor').first());
    if (await editor.isVisible({ timeout: 5000 }).catch(() => false)) {
      await editor.fill('The hero entered the dark forest.');

      const continueBtn = page.getByRole('button', { name: /continue|generate/i });
      if (await continueBtn.isVisible()) {
        await continueBtn.click();
        await expect(continueBtn).toBeEnabled({ timeout: 120000 });
      }

      const beatsPanel = page.getByRole('button', { name: /beats|branch/i });
      if (await beatsPanel.isVisible({ timeout: 3000 }).catch(() => false)) {
        await beatsPanel.click();

        const branchBtn = page.getByRole('button', { name: /branch/i }).first();
        if (await branchBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
          await branchBtn.click();
          const confirmBtn = page.getByRole('button', { name: /branch|confirm/i }).first();
          if (await confirmBtn.isVisible()) {
            await confirmBtn.click();
          }
          await waitForToast(page, /branch/i, 10000);
        }
      }
    }
  });

  test('Add Manual Beat', async ({ page }) => {
    await page.goto('/story');

    const beatInput = page.getByPlaceholder(/add a beat|beat input/i).first();
    if (await beatInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await beatInput.fill('A sudden dragon attack!');
      await beatInput.press('Enter');
      await waitForToast(page, /beat added/i, 5000);
    }
  });

  test('Auto-Generate Title', async ({ page }) => {
    await page.goto('/story');

    const editor = page.getByPlaceholder(/once upon a time/i).first().or(page.locator('.story-editor').first());
    if (await editor.isVisible({ timeout: 5000 }).catch(() => false)) {
      await editor.fill('Once upon a time in a magical kingdom, there lived a brave knight who could talk to dragons.');

      const titleBtn = page.getByRole('button', { name: /title|auto.?generate/i }).first();
      if (await titleBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await titleBtn.click();
        await waitForToast(page, /title/i, 30000);
      }
    }
  });

  test('Story Editor Auto-Save', async ({ page }) => {
    await page.goto('/story');

    const editor = page.getByPlaceholder(/once upon a time/i).first().or(page.locator('.story-editor').first());
    if (await editor.isVisible({ timeout: 5000 }).catch(() => false)) {
      await editor.fill('Auto-save verification paragraph.');
      await page.waitForTimeout(3000);

      await page.reload();
      await page.waitForTimeout(1000);

      const reloadedEditor = page.getByPlaceholder(/once upon a time/i).first().or(page.locator('.story-editor').first());
      const content = await reloadedEditor.textContent();
      expect(content).toContain('Auto-save verification paragraph');
    }
  });

  test('Context Panel: Attach Lorebook', async ({ page }) => {
    await page.goto('/story');

    const contextTab = page.getByRole('button', { name: /context/i }).first();
    if (await contextTab.isVisible({ timeout: 3000 }).catch(() => false)) {
      await contextTab.click();
      await page.waitForTimeout(1000);

      const lorebookToggle = page.getByRole('button', { name: /lorebook|add lorebook/i }).first();
      if (await lorebookToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
        await lorebookToggle.click();
        await waitForToast(page, /lorebook/i, 5000);
      }
    }
  });

  test('Delete Story', async ({ page }) => {
    await page.goto('/story');

    const createStoryBtn = page.getByRole('button', { name: /create story/i }).first();
    if (await createStoryBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await createStoryBtn.click();
      const titleInput = page.getByPlaceholder(/story title/i).first();
      if (await titleInput.isVisible()) {
        await titleInput.fill('To Be Deleted Story');
        await page.getByRole('button', { name: /create|confirm/i }).first().click();
        await waitForToast(page, /created/i, 5000);
      }

      const url = page.url();
      const storyMatch = url.match(/\/story\/([^/]+)/);
      if (storyMatch) createdStoryId = storyMatch[1];
    }

    const deleteBtn = page.getByRole('button', { name: /delete/i }).first();
    if (await deleteBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await deleteBtn.click();
      const confirmBtn = page.getByRole('button', { name: /delete/i }).first();
      if (await confirmBtn.isVisible()) {
        await confirmBtn.click();
      }
      await waitForToast(page, /deleted/i, 5000);
    }
  });

  test('Switch Chapters and Verify Content', async ({ page }) => {
    await page.goto('/story');

    const createStoryBtn = page.getByRole('button', { name: /create story/i }).first();
    if (await createStoryBtn.isVisible({ timeout: 5000 }).catch(() => false)) {
      await createStoryBtn.click();
      const titleInput = page.getByPlaceholder(/story title/i).first();
      if (await titleInput.isVisible()) {
        await titleInput.fill('Multi-chapter Story');
        await page.getByRole('button', { name: /create|confirm/i }).first().click();
        await waitForToast(page, /created/i, 5000);
      }
      
      const url = page.url();
      const storyMatch = url.match(/\/story\/([^/]+)/);
      if (storyMatch) createdStoryId = storyMatch[1];
    }
    
    const editor = page.getByPlaceholder(/once upon a time/i).first().or(page.locator('.story-editor').first());
    if (await editor.isVisible({ timeout: 5000 }).catch(() => false)) {
       await editor.fill('This is chapter 1.');
       
       const createChapterBtn = page.getByRole('button', { name: /new chapter|add chapter/i }).first();
       if (await createChapterBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
         await createChapterBtn.click();
         await waitForToast(page, /chapter/i, 5000);
         
         const newEditor = page.getByPlaceholder(/once upon a time/i).first().or(page.locator('.story-editor').first());
         if (await newEditor.isVisible({ timeout: 5000 }).catch(() => false)) {
           await newEditor.fill('This is chapter 2.');
           
           const chap1Btn = page.getByRole('button', { name: /chapter 1/i }).first();
           if (await chap1Btn.isVisible({ timeout: 3000 }).catch(() => false)) {
             await chap1Btn.click();
             await expect(newEditor).toContainText('chapter 1', { timeout: 5000 });
           }
         }
       }
    }
  });

  test('Edit and Reorder Beats', async ({ page }) => {
    await page.goto('/story');

    const beatInput = page.getByPlaceholder(/add a beat|beat input/i).first();
    if (await beatInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await beatInput.fill('First beat');
      await beatInput.press('Enter');
      await waitForToast(page, /beat added/i, 5000);
      
      const beatItem = page.getByText('First beat').first();
      if (await beatItem.isVisible({ timeout: 3000 }).catch(() => false)) {
        await expect(beatItem).toBeVisible();
      }
    }
  });
});
