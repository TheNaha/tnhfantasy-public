import { test, expect } from '@playwright/test';
import {
  apiGet,
  seedCharacter,
  seedChat,
  seedStory,
  seedLocation,
  seedCampaign,
  cleanupEntities,
  uniqueName,
  expectToast,
} from './fixtures.js';

// CampaignCard is a motion.div with class "group" (action buttons are
// opacity-0 until group-hover). It renders name, description and per-entity
// link count badges. Open/Edit/Delete buttons are exposed via title attrs.
function campaignCard(page, name) {
  return page
    .getByText(name, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"group")][1]');
}

async function openCardActions(page, name) {
  const card = campaignCard(page, name);
  await expect(card).toBeVisible({ timeout: 10000 });
  await card.hover();
  return card;
}

// The dashboard/form modals are plain overlays (no role="dialog"): the
// deepest "fixed inset-0" overlay currently rendered.
function topOverlay(page) {
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

test.describe('Campaigns (World Vault)', () => {
  test.setTimeout(90000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('renders list cards for API-seeded campaigns', async ({ page }) => {
    const campaign = await seedCampaign(page, { name: uniqueName('e2e-campaign') });
    created.push({ kind: 'campaign', id: campaign.id });

    await page.goto('/campaigns');
    await expect(page.getByRole('heading', { level: 1, name: 'Campaigns' })).toBeVisible();

    const card = campaignCard(page, campaign.name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText(campaign.description);
  });

  test('dashboard modal shows linked entity sections (API-seeded campaign)', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    const location = await seedLocation(page, { name: uniqueName('e2e-location') });
    created.push(
      { kind: 'character', id: character.id },
      { kind: 'story', id: story.id },
      { kind: 'chat', id: chat.id },
      { kind: 'location', id: location.id }
    );

    const campaign = await seedCampaign(page, {
      name: uniqueName('e2e-campaign'),
      character_ids: [character.id],
      story_ids: [story.id],
      chat_ids: [chat.id],
      location_ids: [location.id],
    });
    created.push({ kind: 'campaign', id: campaign.id });

    await page.goto('/campaigns');
    const card = await openCardActions(page, campaign.name);
    await card.getByTitle('Open').click();

    const overlay = topOverlay(page);
    await expect(overlay.getByRole('heading', { name: campaign.name, exact: true })).toBeVisible();
    for (const [section, label] of [
      ['Characters', character.name],
      ['Stories', story.title],
      ['Chats', chat.name],
      ['Locations', location.name],
    ]) {
      await expect(overlay.getByText(`${section} (1)`, { exact: true })).toBeVisible();
      await expect(overlay.getByRole('button', { name: label, exact: true })).toBeVisible();
    }

    // Clicking the backdrop (mid-right area, clear of the 256px sidebar and
    // the centered modal) dismisses the modal.
    await overlay.click({ position: { x: 270, y: 650 } });
    await expect(overlay).toBeHidden({ timeout: 5000 });
  });

  test('create campaign via UI form and link entities with pickers', async ({ page }) => {
    const character = await seedCharacter(page, { name: uniqueName('e2e-char') });
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    const chat = await seedChat(page, { name: uniqueName('e2e-chat') });
    const location = await seedLocation(page, { name: uniqueName('e2e-location') });
    created.push(
      { kind: 'character', id: character.id },
      { kind: 'story', id: story.id },
      { kind: 'chat', id: chat.id },
      { kind: 'location', id: location.id }
    );

    const name = uniqueName('e2e-campaign');
    const description = 'A chronicle forged in the e2e furnace.';

    await page.goto('/campaigns');
    await page.getByRole('button', { name: 'New Campaign', exact: true }).click();

    const form = page
      .getByRole('heading', { name: 'New Campaign', exact: true })
      .locator('xpath=ancestor::div[contains(@class,"bg-gray-900")][1]');
    await form.getByPlaceholder('Campaign name').fill(name);
    await form.getByPlaceholder('Overview of this campaign...').fill(description);

    // Entity pickers render one toggle button per entity (label = entity name).
    // The form modal is taller than the viewport without its own scrollbar, so
    // lower sections/buttons sit outside the viewport — dispatch clicks
    // programmatically (known UI limitation, see e2e report).
    await pickEntity(form, character.name);
    await pickEntity(form, story.title);
    await pickEntity(form, chat.name);
    await pickEntity(form, location.name);
    await form.getByRole('button', { name: 'Create', exact: true }).evaluate((el) => el.click());

    await expectToast(page, /Campaign created/);

    const all = await apiGet(page, '/campaigns');
    const saved = all.find((c) => c.name === name);
    expect(saved, 'created campaign must exist via API').toBeTruthy();
    expect(saved.character_ids).toContain(character.id);
    expect(saved.story_ids).toContain(story.id);
    expect(saved.chat_ids).toContain(chat.id);
    expect(saved.location_ids).toContain(location.id);
    created.push({ kind: 'campaign', id: saved.id });

    // Card round-trips: name, description and one count badge per entity type.
    const card = campaignCard(page, name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText(description);
    await expect(card.getByText('1', { exact: true })).toHaveCount(4);

    // Dashboard modal reflects the freshly linked entities.
    await card.hover();
    await card.getByTitle('Open').click();
    const overlay = topOverlay(page);
    await expect(overlay.getByText('Characters (1)', { exact: true })).toBeVisible();
    await expect(overlay.getByText('Stories (1)', { exact: true })).toBeVisible();
    await expect(overlay.getByText('Chats (1)', { exact: true })).toBeVisible();
    await expect(overlay.getByText('Locations (1)', { exact: true })).toBeVisible();
  });

  test('edit campaign persists changes', async ({ page }) => {
    const campaign = await seedCampaign(page, { name: uniqueName('e2e-campaign') });
    created.push({ kind: 'campaign', id: campaign.id });

    const newName = uniqueName('e2e-campaign-renamed');
    await page.goto('/campaigns');

    const card = await openCardActions(page, campaign.name);
    await card.getByTitle('Edit').click();

    const form = page
      .getByRole('heading', { name: 'Edit Campaign', exact: true })
      .locator('xpath=ancestor::div[contains(@class,"bg-gray-900")][1]');
    await form.getByPlaceholder('Campaign name').fill(newName);
    await form.getByPlaceholder('Overview of this campaign...').fill('An updated chronicle.');
    // Update button sits below the viewport in the non-scrolling form modal —
    // dispatch the click programmatically.
    await form.getByRole('button', { name: 'Update', exact: true }).evaluate((el) => el.click());

    await expectToast(page, /Campaign updated/);
    await expect(campaignCard(page, newName)).toBeVisible({ timeout: 10000 });

    const saved = await apiGet(page, `/campaigns/${campaign.id}`);
    expect(saved.name).toBe(newName);
    expect(saved.description).toBe('An updated chronicle.');
  });

  test('delete campaign via card action with confirmation', async ({ page }) => {
    const campaign = await seedCampaign(page, { name: uniqueName('e2e-campaign') });
    created.push({ kind: 'campaign', id: campaign.id });

    await page.goto('/campaigns');
    const card = await openCardActions(page, campaign.name);
    await card.getByTitle('Delete').click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Delete Campaign', { exact: true })).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete', exact: true }).click();

    await expectToast(page, /Campaign deleted/);
    await expect(campaignCard(page, campaign.name)).toHaveCount(0);

    const all = await apiGet(page, '/campaigns');
    expect(all.some((c) => c.name === campaign.name)).toBe(false);
  });
});