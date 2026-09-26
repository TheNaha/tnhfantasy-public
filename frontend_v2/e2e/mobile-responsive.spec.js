import { test, expect } from '@playwright/test';
import {
  dismissOnboarding,
  seedChat,
  seedStory,
  seedStoryChapter,
  uniqueName,
} from './fixtures.js';

// ---------------------------------------------------------------------------
// Mobile / responsive coverage.
//
// Runs only in the 'mobile-chromium' project (Pixel 5 viewport, hasTouch).
// The desktop 'chromium' project deliberately ignores this file — desktop
// behavior is covered by the other specs, so everything here targets the
// lg:hidden mobile chrome: hamburger menu, bottom tab bars, doubled
// generator bars. Keep tests strict — no conditional no-ops.
// ---------------------------------------------------------------------------

async function openMobileMenu(page) {
  await page.getByRole('button', { name: 'Toggle mobile menu' }).click();
  await expect(page.getByRole('button', { name: 'Toggle mobile menu' })).toHaveAttribute(
    'aria-expanded',
    'true'
  );
}

async function expectSidebarClosed(page) {
  await expect(page.getByRole('button', { name: 'Toggle mobile menu' })).toHaveAttribute(
    'aria-expanded',
    'false'
  );
  await expect
    .poll(() => page.locator('#mobile-sidebar').boundingBox().then((b) => b && b.x))
    .toBeLessThan(0);
}

test.describe.serial('mobile chrome', () => {
  test('hamburger menu opens, navigates, closes', async ({ page }) => {
    await dismissOnboarding(page);
    await page.goto('/');
    const hamburger = page.getByRole('button', { name: 'Toggle mobile menu' });
    await expect(hamburger).toBeVisible();
    await expect(page.locator('#mobile-sidebar')).toBeVisible();
    await expectSidebarClosed(page);

    await openMobileMenu(page);
    await expect(page.locator('#mobile-sidebar')).toBeVisible();
    await expect
      .poll(() => page.locator('#mobile-sidebar').boundingBox().then((b) => b && b.x))
      .toBeGreaterThanOrEqual(0);
    await expect(page.getByRole('button', { name: 'Close mobile menu' })).toBeVisible();

    await page.getByRole('link', { name: 'Gallery', exact: true }).click();
    await expect(page).toHaveURL(/\/gallery$/);
    await expectSidebarClosed(page);

    await openMobileMenu(page);
    await page.getByRole('button', { name: 'Close mobile menu' }).click();
    await expectSidebarClosed(page);
  });

  test('hamburger menu works from full-bleed chat page', async ({ page }) => {
    await page.goto('/chat');
    await expect(page.getByRole('button', { name: 'Toggle mobile menu' })).toBeVisible();

    await openMobileMenu(page);
    await page.getByRole('link', { name: 'Simple Generate' }).click();
    await expect(page).toHaveURL(/\/generate$/);
    await expectSidebarClosed(page);
  });

  test('question-mark opens the keyboard shortcuts modal; Escape closes it', async ({ page }) => {
    await dismissOnboarding(page);
    await page.goto('/');
    // Wait for React to mount the shortcut handler (renders the mobile header).
    await expect(page.getByRole('button', { name: 'Toggle mobile menu' })).toBeVisible();
    await page.keyboard.press('?');
    await expect(page.getByText('Show this help')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByText('Show this help')).toBeHidden();
  });

  test('desktop viewport restores desktop chrome (no hamburger, no bottom tabs)', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto('/chat');
    await expect(page.getByRole('button', { name: 'Toggle mobile menu' })).toBeHidden();
    await expect(page.getByRole('navigation', { name: 'Chat workspace navigation' })).toBeHidden();
    const sidebarBox = await page.locator('#mobile-sidebar').boundingBox();
    expect(sidebarBox.x).toBe(0);
  });
});

test.describe.serial('chat workspace on mobile', () => {
  test('bottom tabs switch chats/roleplay/context panels', async ({ page }) => {
    const chat = await seedChat(page, { name: uniqueName('mobile-chat') });

    // The workspace auto-selects the newest chat, so the roleplay panel opens
    // with it active.
    await page.goto('/chat');
    const tabs = page.getByRole('navigation', { name: 'Chat workspace navigation' });
    await expect(tabs).toBeVisible();
    const chatsTab = tabs.getByRole('button', { name: 'Chats', exact: true });
    const roleplayTab = tabs.getByRole('button', { name: 'Roleplay', exact: true });
    const contextTab = tabs.getByRole('button', { name: 'Context', exact: true });

    await expect(roleplayTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: chat.name })).toBeVisible();
    await expect(page.getByText('No character · as Test User')).toBeVisible();

    await chatsTab.click();
    await expect(chatsTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: new RegExp(chat.name) })).toBeVisible();

    await page.getByRole('button', { name: new RegExp(chat.name) }).click();
    await expect(roleplayTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: chat.name })).toBeVisible();

    await contextTab.click();
    await expect(contextTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: 'Context & Settings' })).toBeVisible();

    await page.getByRole('button', { name: 'Close context panel' }).click();
    await expect(roleplayTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: 'Context & Settings' })).toBeHidden();
    await expect(page.getByRole('heading', { name: chat.name })).toBeVisible();
  });
});

test.describe.serial('story sandbox on mobile', () => {
  test('bottom tabs switch stories/write/context panels', async ({ page }) => {
    const story = await seedStory(page, { title: uniqueName('mobile-story') });
    const chapter = await seedStoryChapter(page, story.id, {
      title: uniqueName('mobile-chapter'),
    });

    await page.goto('/story');
    const tabs = page.getByRole('navigation', { name: 'Story sandbox navigation' });
    await expect(tabs).toBeVisible();
    const storiesTab = tabs.getByRole('button', { name: 'Stories', exact: true });
    const writeTab = tabs.getByRole('button', { name: 'Write', exact: true });
    const contextTab = tabs.getByRole('button', { name: 'Context', exact: true });

    await expect(writeTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('No Story Selected')).toBeVisible();

    await storiesTab.click();
    await expect(storiesTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByPlaceholder('New story title...')).toBeVisible();
    await expect(page.getByText('No stories yet. Create one above.')).toBeHidden();
    await expect(page.getByRole('button', { name: new RegExp(story.title) })).toBeVisible();

    await page.getByRole('button', { name: new RegExp(story.title) }).click();
    await expect(writeTab).toHaveAttribute('aria-pressed', 'true');
    // The chapter auto-selector navigates to the first chapter shortly after a
    // story is chosen — accept either URL form.
    await expect(page).toHaveURL(new RegExp(`/story/${story.id}(/chapter/[^/]+)?$`));
    await expect(page.getByText('No Story Selected')).toBeHidden();

    await contextTab.click();
    await expect(contextTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: 'Story Context' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'AI Model Settings' })).toBeVisible();

    // The chapter editor only renders once a chapter is selected — open the
    // seeded chapter directly to prove the write panel renders it on mobile.
    await page.goto(`/story/${story.id}/chapter/${chapter.id}`);
    await expect(writeTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('textarea').first()).toBeVisible();

    await storiesTab.click();
    await expect(storiesTab).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('button', { name: new RegExp(story.title) })).toBeVisible();
  });
});

test.describe.serial('generators on mobile', () => {
  function visibleGenerate(page) {
    return page.getByRole('button', { name: 'Generate', exact: true }).filter({ visible: true });
  }

  test('simple generator shows only the fixed mobile generate bar at the bottom', async ({
    page,
  }) => {
    await page.goto('/generate');
    // The desktop bar carries `hidden md:block`, so on mobile it is excluded
    // from the accessibility tree entirely — exactly one Generate remains.
    await expect(page.getByRole('button', { name: 'Generate', exact: true })).toHaveCount(1);
    await expect(visibleGenerate(page)).toHaveCount(1);

    const box = await visibleGenerate(page).boundingBox();
    expect(box).not.toBeNull();
    const viewport = page.viewportSize();
    expect(box.y).toBeGreaterThan(viewport.height - 140);
  });

  test('simple generator mobile bar enables when prompt is filled', async ({ page }) => {
    await page.goto('/generate');
    const prompt = page.getByPlaceholder('Describe what you want to create...').first();
    const mobileGenerate = visibleGenerate(page);

    await prompt.fill('');
    await expect(mobileGenerate).toBeDisabled();
    await prompt.fill('a floating city at dusk');
    await expect(mobileGenerate).toBeEnabled();
  });

  test('img2img and inpaint keep a single visible action bar on mobile', async ({ page }) => {
    await page.goto('/img2img');
    await expect(
      page.getByRole('button', { name: 'Generate Img2Img', exact: true }).filter({ visible: true })
    ).toHaveCount(1);
    await expect(page.getByTitle('Add to queue').filter({ visible: true })).toHaveCount(1);

    await page.goto('/inpaint');
    await expect(
      page.getByRole('button', { name: 'Generate Inpaint', exact: true }).filter({ visible: true })
    ).toHaveCount(1);
    await expect(page.getByTitle('Add to queue').filter({ visible: true })).toHaveCount(1);
  });
});