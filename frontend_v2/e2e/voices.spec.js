import { test, expect } from '@playwright/test';
import {
  apiGet,
  seedVoice,
  cleanupEntities,
  uniqueName,
  expectToast,
} from './fixtures.js';

// Voice cards share the row layout: flex with "justify-between" on the card
// root. Actions (Preview/Edit/Delete) are title-attributed icon buttons.
function voiceCard(page, name) {
  return page
    .getByText(name, { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"justify-between")][1]');
}

// The create/edit form is an inline motion.div (no role="dialog").
function voiceForm(page, heading) {
  return page
    .getByRole('heading', { name: heading, exact: true })
    .locator('xpath=ancestor::div[contains(@class,"bg-gray-900")][1]');
}

test.describe('Voices (World Vault)', () => {
  test.setTimeout(90000);

  let created = [];

  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('list renders seeded voice model details', async ({ page }) => {
    const voice = await seedVoice(page, {
      name: uniqueName('e2e-voice'),
      type: 'bark',
      voice_profile: 'bark_speaker',
      language: 'en',
      preview_text: 'A quick bark test for the e2e suite.',
    });
    created.push({ kind: 'voice', id: voice.id });

    await page.goto('/voices');
    await expect(page.getByRole('heading', { level: 1, name: 'Voice Models' })).toBeVisible();

    const card = voiceCard(page, voice.name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText('bark');
    await expect(card).toContainText('Profile: bark_speaker');
    await expect(card).toContainText('Preview: "A quick bark test for the e2e suite."');
  });

  test('create voice model via UI form', async ({ page }) => {
    const name = uniqueName('e2e-voice');
    const profile = 'e2e_speaker';
    const preview = 'Hello traveler, the e2e suite greets you.';

    await page.goto('/voices');
    await page.getByRole('button', { name: 'Create Voice', exact: true }).first().click();

    const form = voiceForm(page, 'New Voice Model');
    await form.getByPlaceholder('Voice model name').fill(name);
    await form.getByPlaceholder('Select type').fill('xtts');
    await form.getByPlaceholder('e.g. test_speaker, default').fill(profile);
    await form.getByPlaceholder('e.g. en, es, fr').fill('en');
    await form.getByPlaceholder('Sample text for preview').fill(preview);
    await form.getByPlaceholder('Optional description').fill('Created by the e2e suite.');
    await form.getByRole('button', { name: 'Create', exact: true }).click();

    await expectToast(page, /Voice model created/);

    const card = voiceCard(page, name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText('xtts');
    await expect(card).toContainText(`Profile: ${profile}`);
    await expect(card).toContainText(`Preview: "${preview}"`);

    const all = await apiGet(page, '/v2/voices');
    const saved = all.find((v) => v.name === name);
    expect(saved, 'created voice must exist via API').toBeTruthy();
    expect(saved.type).toBe('xtts');
    expect(saved.voice_profile).toBe(profile);
    expect(saved.preview_text).toBe(preview);
    created.push({ kind: 'voice', id: saved.id });
  });

  test('edit voice model persists changes', async ({ page }) => {
    const voice = await seedVoice(page, { name: uniqueName('e2e-voice'), voice_profile: 'original_speaker' });
    created.push({ kind: 'voice', id: voice.id });

    const newName = uniqueName('e2e-voice-renamed');
    await page.goto('/voices');

    const card = voiceCard(page, voice.name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await card.getByTitle('Edit').click();

    const form = voiceForm(page, 'Edit Voice Model');
    await form.getByPlaceholder('Voice model name').fill(newName);
    await form.getByPlaceholder('e.g. test_speaker, default').fill('updated_speaker');
    await form.getByPlaceholder('Sample text for preview').fill('Updated preview line.');
    await form.getByRole('button', { name: 'Update', exact: true }).click();

    await expectToast(page, /Voice model updated/);
    await expect(voiceCard(page, newName)).toBeVisible({ timeout: 10000 });

    const saved = await apiGet(page, `/v2/voices/${voice.id}`);
    expect(saved.name).toBe(newName);
    expect(saved.voice_profile).toBe('updated_speaker');
    expect(saved.preview_text).toBe('Updated preview line.');
  });

  test('delete voice model via card action with confirmation', async ({ page }) => {
    const voice = await seedVoice(page, { name: uniqueName('e2e-voice') });
    created.push({ kind: 'voice', id: voice.id });

    await page.goto('/voices');
    const card = voiceCard(page, voice.name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await card.getByTitle('Delete').click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Are you sure you want to delete "', { exact: false })).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete', exact: true }).click();

    await expectToast(page, /Voice model deleted/);
    await expect(voiceCard(page, voice.name)).toHaveCount(0);

    const all = await apiGet(page, '/v2/voices');
    expect(all.some((v) => v.name === voice.name)).toBe(false);
  });
});