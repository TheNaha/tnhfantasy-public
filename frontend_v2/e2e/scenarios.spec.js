import { test, expect } from '@playwright/test';
import {
  apiGet,
  expectToast,
  inlineForm,
  rowCard,
  seedScenario,
  seedStory,
  trackEntity,
  uniqueName,
} from './fixtures.js';

test.describe('Scenarios (World Vault)', () => {
  test.setTimeout(90000);

  test('create scenario via UI form', async ({ page }) => {
    const name = uniqueName('e2e-scenario');
    const description = 'A realm where the sun never rises.';
    const promptTemplate = 'You are the Keeper of the E2ELAND gates. Every choice echoes through the mist.';

    await page.goto('/scenarios');
    await page.getByRole('button', { name: 'Create Scenario', exact: true }).first().click();

    const form = inlineForm(page, 'New Scenario');
    await form.getByPlaceholder('Scenario name').fill(name);
    await form.getByPlaceholder('What is this scenario about?').fill(description);
    await form.getByPlaceholder('The system prompt or starter prompt for this scenario...').fill(promptTemplate);
    await form.getByRole('button', { name: 'Create', exact: true }).click();

    await expectToast(page, /Scenario created/);

    const card = rowCard(page, name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await expect(card).toContainText(description);
    await expect(card).toContainText(promptTemplate);

    const all = await apiGet(page, '/scenarios');
    const saved = all.find((s) => s.name === name);
    expect(saved, 'created scenario must exist via API').toBeTruthy();
    expect(saved.description).toBe(description);
    expect(saved.prompt_template).toBe(promptTemplate);
    trackEntity(page, 'scenario', saved.id);
  });

  test('apply scenario: UI flow fires dialogs; backend apply sets story scenario_id', async ({ page }) => {
    const scenario = await seedScenario(page, { name: uniqueName('e2e-scenario') });
    trackEntity(page, 'scenario', scenario.id);
    const story = await seedStory(page, { title: uniqueName('e2e-story') });
    trackEntity(page, 'story', story.id);

    await page.goto('/scenarios');
    const card = rowCard(page, scenario.name);
    await expect(card).toBeVisible({ timeout: 10000 });

    // The Apply action uses two native window.prompt() calls: target type,
    // then target id. Accept them in order; the UI apply now round-trips
    // (camelCase keys fixed) so the story ends up linked.
    const dialogAnswers = ['story', story.id];
    let dialogIndex = 0;
    page.on('dialog', (d) => d.accept(dialogAnswers[dialogIndex++] ?? ''));

    await card.getByTitle('Apply to chat or story').click();
    await expectToast(page, /Applied to story/);

    const savedStory = await apiGet(page, `/stories/${story.id}`);
    expect(savedStory.scenario_id).toBe(scenario.id);
  });

  test('edit scenario persists changes', async ({ page }) => {
    const scenario = await seedScenario(page, { name: uniqueName('e2e-scenario') });
    trackEntity(page, 'scenario', scenario.id);

    const newName = uniqueName('e2e-scenario-renamed');
    await page.goto('/scenarios');

    const card = rowCard(page, scenario.name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await card.getByTitle('Edit').click();

    const form = inlineForm(page, 'Edit Scenario');
    await form.getByPlaceholder('Scenario name').fill(newName);
    await form.getByPlaceholder('What is this scenario about?').fill('An updated description.');
    await form.getByPlaceholder('The system prompt or starter prompt for this scenario...').fill('Updated: the mist has lifted.');
    await form.getByRole('button', { name: 'Update', exact: true }).click();

    await expectToast(page, /Scenario updated/);
    await expect(rowCard(page, newName)).toBeVisible({ timeout: 10000 });

    const saved = await apiGet(page, `/scenarios/${scenario.id}`);
    expect(saved.name).toBe(newName);
    expect(saved.description).toBe('An updated description.');
    expect(saved.prompt_template).toBe('Updated: the mist has lifted.');
  });

  test('delete scenario via card action with confirmation', async ({ page }) => {
    const scenario = await seedScenario(page, { name: uniqueName('e2e-scenario') });
    trackEntity(page, 'scenario', scenario.id);

    await page.goto('/scenarios');
    const card = rowCard(page, scenario.name);
    await expect(card).toBeVisible({ timeout: 10000 });
    await card.getByTitle('Delete').click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Are you sure you want to delete "', { exact: false })).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete', exact: true }).click();

    await expectToast(page, /Scenario deleted/);
    await expect(rowCard(page, scenario.name)).toHaveCount(0);

    const all = await apiGet(page, '/scenarios');
    expect(all.some((s) => s.name === scenario.name)).toBe(false);
  });
});