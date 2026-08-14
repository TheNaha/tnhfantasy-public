import { expect } from '@playwright/test';

async function listModels(page, directory) {
  const data = await page.request.get(`/api/files?directory=${directory}&limit=100`).then(r => r.json());
  return data.files || [];
}

function pickSingleVersionModel(models) {
  const real = models.filter((m) => !/\.(downloading|part|crdownload|tmp|temp)$/i.test(m.name || ''));
  const available = real.filter((m) =>
    Object.values(m.provider_statuses || {}).some(
      (s) => s && ['installed', 'ready'].includes(s.status)
    )
  );
  const pool = available.length ? available : real;
  return (
    pool.find((m) => !m.versions || m.versions.length <= 1) ||
    pool[0] ||
    models[0]
  );
}

async function selectModelFromDialog(dialog, model) {
  const cardText = model.display_name || model.name;
  const search = dialog.getByPlaceholder('Search models by name, tags, description...');
  await search.fill(cardText);
  await dialog.getByText(cardText).first().click();
  const dropdown = dialog.getByText('Select Version').locator('..').locator('..');
  const firstVersion = dropdown.locator('div').last().locator('button').first();
  if (await firstVersion.isVisible({ timeout: 3000 }).catch(() => false)) {
    await firstVersion.click();
  }
  await expect(dialog).toBeHidden();
}

async function selectCheckpoint(page, model, label = 'Checkpoint / UNET') {
  await page.getByRole('button', { name: `Select ${label}` }).click();
  await selectModelFromDialog(page.getByRole('dialog'), model);
  const dismiss = page.getByRole('button', { name: 'Dismiss' });
  if (await dismiss.isVisible({ timeout: 3000 }).catch(() => false)) await dismiss.click();
}

function visibleGenerate(page) {
  return page.getByRole('button', { name: 'Generate', exact: true }).filter({ visible: true });
}

export {
  listModels,
  pickSingleVersionModel,
  selectModelFromDialog,
  selectCheckpoint,
  visibleGenerate,
};
