import { test, expect } from '@playwright/test';
import {
  apiGet,
  expectToast,
  seedWorld,
  seedCharacter,
  seedChat,
  seedLocation,
  seedStory,
  trackEntity,
  uniqueName,
} from './fixtures.js';

// WorldCard is a motion.div with class "group" (action buttons are
// opacity-0 until group-hover). It renders name, description and per-entity
// link count badges. Open/Edit/Delete buttons are exposed via title attrs.
function worldCard(page, name) {
  return page
    .getByText(name, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"group")][1]');
}

async function openCardActions(page, name) {
  const card = worldCard(page, name);
  await expect(card).toBeVisible({ timeout: 10000 });
  await card.hover();
  return card;
}

// The form/dashboard modals are overlays; both now carry role="dialog", so the
// deepest one currently rendered is the dialog for the action just performed.
function topDialog(page) {
  return page.locator('.fixed.inset-0').last();
}

// Click an entity-picker row. The form modal can exceed the viewport height
// with no internal scrollbar, so rows below the fold can't be actioned
// normally — dispatch the click directly on the button element.
function pickEntity(form, label) {
  return form
    .getByRole('button', { name: label, exact: true })
    .evaluate((el) => el.click());
}

test.describe('Worlds (World Vault)', () => {
  test.setTimeout(90000);

  test('renders list cards for API-seeded worlds', async ({ page }) => {
    const world = await seedWorld(page, { name: uniqueName('e2e-world') });
    trackEntity(page, 'world', world.id);

    await page.goto('/worlds');
    await expect(page.getByRole('heading', { level: 1, name: 'Worlds' })).toBeVisible();

    const card = worldCard(page, world.name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText(world.description);
  });

  test('the retired /campaigns URL redirects to /worlds', async ({ page }) => {
    await page.goto('/campaigns');
    await expect(page).toHaveURL(/\/worlds$/);
    await expect(page.getByRole('heading', { level: 1, name: 'Worlds' })).toBeVisible();
  });

  test('a failed list request says so instead of rendering an empty vault', async ({ page }) => {
    // The defect this page replaced: `/api/v2/campaigns` 404'd, the page had no
    // `isError` branch, and the result was a plausible "No campaigns yet" with a
    // working button. Intercepted here so the branch is proven, not assumed.
    await page.route('**/api/v2/worlds', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"boom"}' }),
    );

    await page.goto('/worlds');
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByRole('heading', { name: /could not load your worlds/i })).toBeVisible();
    await expect(page.getByText('No worlds yet')).toHaveCount(0);
  });

  test('dashboard modal shows linked entity sections (API-seeded world)', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    const location = await seedLocation(page, { name: uniqueName('e2e-location') });
    trackEntity(page, 'character', character.id);
    trackEntity(page, 'story', story.id);
    trackEntity(page, 'chat', chat.id);
    trackEntity(page, 'location', location.id);

    const world = await seedWorld(page, {
      name: uniqueName('e2e-world'),
      character_ids: [character.id],
      story_ids: [story.id],
      chat_ids: [chat.id],
      location_ids: [location.id],
    });
    trackEntity(page, 'world', world.id);

    await page.goto('/worlds');
    const card = await openCardActions(page, world.name);
    await card.getByTitle('Open').click();

    const overlay = topDialog(page);
    await expect(overlay.getByRole('heading', { name: world.name, exact: true })).toBeVisible();
    for (const [section, label] of [
      ['Characters', character.name],
      ['Stories', story.title],
      ['Chats', chat.name],
      ['Locations', location.name],
    ]) {
      await expect(overlay.getByText(`${section} (1)`, { exact: true })).toBeVisible();
      await expect(overlay.getByRole('button', { name: label, exact: true })).toBeVisible();
    }

    // Escape closes it — the form/dashboard overlays now use useEscapeKey, and
    // KeyboardShortcutsModal advertises "Esc → Close modals".
    await page.keyboard.press('Escape');
    await expect(overlay).toBeHidden({ timeout: 5000 });
  });

  test('create world via UI form and link entities with pickers', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    const location = await seedLocation(page, { name: uniqueName('e2e-location') });
    trackEntity(page, 'character', character.id);
    trackEntity(page, 'story', story.id);
    trackEntity(page, 'chat', chat.id);
    trackEntity(page, 'location', location.id);

    const name = uniqueName('e2e-world');
    const description = 'A realm forged in the e2e furnace.';

    await page.goto('/worlds');
    await page.getByRole('button', { name: 'New World', exact: true }).click();

    const form = page
      .getByRole('heading', { name: 'New World', exact: true })
      .locator('xpath=ancestor::div[contains(@class,"bg-gray-900")][1]');
    await form.getByPlaceholder('World name').fill(name);
    await form.getByPlaceholder('Overview of this world...').fill(description);

    // Entity pickers render one toggle button per entity (label = entity name).
    await pickEntity(form, character.name);
    await pickEntity(form, story.title);
    await pickEntity(form, chat.name);
    await pickEntity(form, location.name);
    await form.getByRole('button', { name: 'Create', exact: true }).evaluate((el) => el.click());

    await expectToast(page, /World created/);

    const all = await apiGet(page, '/worlds');
    const saved = all.find((w) => w.name === name);
    expect(saved, 'created world must exist via API').toBeTruthy();
    expect(saved.character_ids).toContain(character.id);
    expect(saved.story_ids).toContain(story.id);
    expect(saved.chat_ids).toContain(chat.id);
    expect(saved.location_ids).toContain(location.id);
    trackEntity(page, 'world', saved.id);

    // Card round-trips: name, description and one count badge per entity type.
    const card = worldCard(page, name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText(description);
    await expect(card.getByText('1', { exact: true })).toHaveCount(4);

    // Dashboard modal reflects the freshly linked entities.
    await card.hover();
    await card.getByTitle('Open').click();
    const overlay = topDialog(page);
    await expect(overlay.getByText('Characters (1)', { exact: true })).toBeVisible();
    await expect(overlay.getByText('Stories (1)', { exact: true })).toBeVisible();
    await expect(overlay.getByText('Chats (1)', { exact: true })).toBeVisible();
    await expect(overlay.getByText('Locations (1)', { exact: true })).toBeVisible();
  });

  test('edit world persists changes', async ({ page }) => {
    const world = await seedWorld(page, { name: uniqueName('e2e-world') });
    trackEntity(page, 'world', world.id);

    const newName = uniqueName('e2e-world-renamed');
    await page.goto('/worlds');

    const card = await openCardActions(page, world.name);
    await card.getByTitle('Edit').click();

    const form = page
      .getByRole('heading', { name: 'Edit World', exact: true })
      .locator('xpath=ancestor::div[contains(@class,"bg-gray-900")][1]');
    await form.getByPlaceholder('World name').fill(newName);
    await form.getByPlaceholder('Overview of this world...').fill('An updated realm.');
    await form.getByRole('button', { name: 'Update', exact: true }).evaluate((el) => el.click());

    await expectToast(page, /World updated/);
    await expect(worldCard(page, newName)).toBeVisible({ timeout: 10000 });

    const saved = await apiGet(page, `/worlds/${world.id}`);
    expect(saved.name).toBe(newName);
    expect(saved.description).toBe('An updated realm.');
  });

  test('delete world via card action with confirmation', async ({ page }) => {
    const world = await seedWorld(page, { name: uniqueName('e2e-world') });
    trackEntity(page, 'world', world.id);

    await page.goto('/worlds');
    const card = await openCardActions(page, world.name);
    await card.getByTitle('Delete').click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Delete World', { exact: true })).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete', exact: true }).click();

    await expectToast(page, /World deleted/);
    await expect(worldCard(page, world.name)).toHaveCount(0);

    const all = await apiGet(page, '/worlds');
    expect(all.some((w) => w.name === world.name)).toBe(false);
  });
});
