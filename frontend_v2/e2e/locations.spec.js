// Module E: Locations — grid, create form, edit, delete, search.
//
// Seed strategy: API-seeded rows via POST /v2/locations for the edit/delete/
// search tests; the create test goes through the real UI modal (tag chips are
// added with the dedicated "Add tag..." input — the FORM_FIELDS tags text
// input would send a string and fail backend validation).

import { test, expect } from '@playwright/test';
import {
  apiGet,
  cleanupEntities,
  expectToast,
  seedLocation,
  uniqueName,
} from './fixtures.js';

const created = [];

test.afterEach(async ({ page }) => {
  await cleanupEntities(page, created.splice(0));
});

// The card for `name` (h3) → its nearest rounded-xl ancestor is the card div.
function locationCard(page, name) {
  return page
    .getByRole('heading', { name })
    .locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]');
}

test.describe('Locations', () => {
  test('page renders heading, subtitle and New Location button', async ({ page }) => {
    await page.goto('/locations');

    await expect(page.getByRole('heading', { level: 1, name: 'Locations' })).toBeVisible();
    await expect(page.getByText('World-building locations for your fantasy universe')).toBeVisible();
    await expect(page.getByRole('button', { name: 'New Location', exact: true })).toBeVisible();
  });

  test('create location via the modal form: toast + card with name, description and tag', async ({ page }) => {
    const name = uniqueName('e2e-location');
    const description = uniqueName('e2e-location-desc');
    const tag = uniqueName('e2e-tag');

    await page.goto('/locations');
    await page.getByRole('button', { name: 'New Location', exact: true }).click();

    await expect(page.getByRole('heading', { name: 'New Location', exact: true })).toBeVisible();
    await page.getByPlaceholder('Location name').fill(name);
    await page.getByPlaceholder('A vivid description of this location...').fill(description);
    await page.getByPlaceholder('Add tag...').fill(tag);
    await page.getByRole('button', { name: 'Add', exact: true }).click();
    await expect(page.getByText(tag, { exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expectToast(page, /Location created/);

    await expect(locationCard(page, name)).toBeVisible();
    await expect(locationCard(page, name).getByText(description)).toBeVisible();
    await expect(locationCard(page, name).getByText(tag, { exact: true })).toBeVisible();

    // Track the created row via API for cleanup.
    const locations = await apiGet(page, '/locations');
    const loc = locations.find((l) => l.name === name);
    expect(loc, 'created location must exist via API').toBeTruthy();
    expect(loc.tags).toContain(tag);
    created.push({ kind: 'location', id: loc.id });
  });

  test('required name validation blocks save', async ({ page }) => {
    await page.goto('/locations');
    await page.getByRole('button', { name: 'New Location', exact: true }).click();

    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await expectToast(page, /Name is required/);
    await expect(page.getByRole('heading', { name: 'New Location', exact: true })).toBeVisible();
  });

  test('edit persists updated description via the modal form', async ({ page }) => {
    const seed = await seedLocation(page, {
      name: uniqueName('e2e-location'),
      description: 'Original description from the seed.',
    });
    created.push({ kind: 'location', id: seed.id });
    const newDescription = uniqueName('e2e-updated-desc');

    await page.goto('/locations');
    const card = locationCard(page, seed.name);
    await expect(card).toBeVisible();

    await card.hover();
    await card.getByTitle('Edit').click();
    await expect(page.getByRole('heading', { name: 'Edit Location', exact: true })).toBeVisible();
    await expect(page.getByPlaceholder('Location name')).toHaveValue(seed.name);

    await page.getByPlaceholder('A vivid description of this location...').fill(newDescription);
    await page.getByRole('button', { name: 'Update', exact: true }).click();
    await expectToast(page, /Location updated/);

    await expect(locationCard(page, seed.name).getByText(newDescription)).toBeVisible();

    const fromApi = await apiGet(page, `/locations/${seed.id}`);
    expect(fromApi.description).toBe(newDescription);
  });

  test('delete removes the card after confirmation', async ({ page }) => {
    const seed = await seedLocation(page, { name: uniqueName('e2e-location') });
    created.push({ kind: 'location', id: seed.id });

    await page.goto('/locations');
    const card = locationCard(page, seed.name);
    await expect(card).toBeVisible();

    await card.hover();
    await card.getByTitle('Delete').click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Delete Location', { exact: true })).toBeVisible();
    await expect(dialog.getByText(`Are you sure you want to delete "${seed.name}"?`)).toBeVisible();
    await dialog.getByRole('button', { name: 'Delete', exact: true }).click();

    await expectToast(page, /Location deleted/);
    await expect.poll(() => page.getByRole('heading', { name: seed.name }).count()).toBe(0);

    created.splice(created.findIndex((e) => e.id === seed.id), 1);
  });

  test('search narrows the grid and empty results show the empty state', async ({ page }) => {
    const alpha = await seedLocation(page, { name: uniqueName('e2e-loc-alpha'), description: 'The amber gate.' });
    const beta = await seedLocation(page, { name: uniqueName('e2e-loc-beta'), description: 'The silver gate.' });
    created.push({ kind: 'location', id: alpha.id }, { kind: 'location', id: beta.id });

    await page.goto('/locations');

    // Search by name.
    const search = page.getByPlaceholder('Search locations...');
    await search.fill(alpha.name);
    await expect(locationCard(page, alpha.name)).toBeVisible();
    await expect(page.getByRole('heading', { name: beta.name })).toHaveCount(0);

    // Search by description.
    await search.fill('silver gate');
    await expect(locationCard(page, beta.name)).toBeVisible();
    await expect(page.getByRole('heading', { name: alpha.name })).toHaveCount(0);

    // No matches → empty state.
    await search.fill(uniqueName('zzz-no-such-location'));
    await expect(page.getByText('No locations yet', { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: alpha.name })).toHaveCount(0);
    await expect(page.getByRole('heading', { name: beta.name })).toHaveCount(0);
  });
});