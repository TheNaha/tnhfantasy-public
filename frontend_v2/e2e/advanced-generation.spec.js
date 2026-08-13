import { test, expect } from '@playwright/test';
import {
  apiGet,
  uniqueName,
  expectToast,
  waitForJob,
  cleanupEntities,
} from './fixtures.js';

const JOB_TIMEOUT = 360000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function listModels(page, directory) {
  const data = await apiGet(page, `/files?directory=${directory}&limit=100`);
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

// The Sampling browser lives in its own glass panel headed by an <h3>; the
// Steps/CFG/Clip Skip labels are scoped to it because identical label text
// (e.g. "Steps") also exists inside the Enhancements section.
const samplingPanel = (page) => page.locator('h3', { hasText: /^Sampling$/ }).locator('..');

async function expandEnhancements(page) {
  await page.getByRole('button', { name: /Enhancements/ }).click();
  await expect(page.getByRole('button', { name: /Enhancements/ })).toHaveAttribute(
    'aria-expanded',
    'true'
  );
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('Advanced Generation Settings (Module G)', () => {
  test.setTimeout(240000);

  const created = [];
  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Simple: auto-randomize toggle flips, seed input refreshes', async ({ page }) => {
    await page.goto('/generate');

    // Default setting has auto-randomize ON (settingsStore default)
    const toggle = page.locator('button[title^="Auto-randomize"]').first();
    await expect(toggle).toHaveAttribute('title', 'Auto-randomize ON');
    await toggle.click();
    await expect(toggle).toHaveAttribute('title', 'Auto-randomize OFF');
    await toggle.click();
    await expect(toggle).toHaveAttribute('title', 'Auto-randomize ON');

    const seedInput = page.getByTitle('Randomize seed').locator('..').locator('input[type="number"]');
    const before = await seedInput.inputValue();
    await page.getByTitle('Randomize seed').click();
    const after = await seedInput.inputValue();
    expect(after).not.toBe(before);
  });

  test('Simple: locking steps disables its inputs; sampler lock disables select', async ({ page }) => {
    await page.goto('/generate');

    const panel = samplingPanel(page);
    const stepsLabel = panel.locator('label', { hasText: /^Steps$/ });
    const stepsInput = stepsLabel.locator('..').locator('input[type="number"]');
    await expect(stepsInput).toBeEnabled();

    await stepsLabel.getByRole('button', { name: 'Lock parameter' }).click();
    await expect(stepsInput).toBeDisabled();
    await expect(stepsLabel.getByRole('button', { name: 'Unlock parameter' })).toBeVisible();

    await stepsLabel.getByRole('button', { name: 'Unlock parameter' }).click();
    await expect(stepsInput).toBeEnabled();

    const samplerLabel = panel.locator('label', { hasText: /^Sampler$/ });
    const samplerSelect = samplerLabel.locator('..').locator('..').locator('select');
    await samplerLabel.locator('..').getByRole('button', { name: 'Lock parameter' }).click();
    await expect(samplerSelect).toBeDisabled();
  });

  test('Simple: enhancement sub-controls accept input and re-lock when disabled', async ({ page }) => {
    await page.goto('/generate');
    await expandEnhancements(page);

    // Hi-Res Fix sub-inputs become editable
    await page.getByLabel('Hi-Res Fix').check();
    const hiresScale = page.getByText(/^Scale$/).locator('..').locator('input[type="number"]');
    await hiresScale.fill('2');
    await expect(hiresScale).toHaveValue('2');

    // ADetailer model + prompt + masked-only checkbox
    await page.getByLabel('ADetailer').check();
    await page.getByPlaceholder('e.g. detailed face, blue eyes').fill('detailed face, sharp eyes');
    await expect(page.getByPlaceholder('e.g. detailed face, blue eyes')).toHaveValue('detailed face, sharp eyes');
    await page.getByLabel('Inpaint Masked Only').check();
    await expect(page.getByLabel('Inpaint Masked Only')).toBeChecked();

    // PAG scale and latent upscale multiplier
    await page.getByLabel('PAG (Perturbed Attention Guidance)').check();
    const pagScale = page.getByText(/^PAG Scale$/).locator('..').locator('input[type="number"]');
    await pagScale.fill('2.5');
    await expect(pagScale).toHaveValue('2.5');

    await page.getByLabel('Latent Upscale').check();
    const multiplier = page.getByText(/^Scale Multiplier$/).locator('..').locator('input[type="number"]');
    await multiplier.fill('1.75');
    await expect(multiplier).toHaveValue('1.75');

    // Disabling hides the wrapper again (max-h-0 wrappers stay "visible" to
    // Playwright, so assert the wrapper class like the suite does elsewhere).
    // "Scale" lives in a nested grid, so the wrapper is three levels up.
    await page.getByLabel('Hi-Res Fix').uncheck();
    await expect(page.getByText(/^Scale$/).locator('..').locator('..').locator('..')).toHaveClass(/pointer-events-none/);
  });

  test('Simple: parameter presets save and reload the sampling config', async ({ page }) => {
    const presetName = uniqueName('e2e-preset');
    await page.goto('/generate');

    const panel = samplingPanel(page);
    const stepsInput = panel.locator('label', { hasText: /^Steps$/ }).locator('..').locator('input[type="number"]');
    await stepsInput.fill('34');

    await page.getByTitle('Manage Presets').click();
    await expect(page.getByText('Parameter Presets')).toBeVisible();
    await page.getByRole('button', { name: 'Save Current' }).click();
    await page.getByPlaceholder('Preset Name').fill(presetName);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expectToast(page, /Preset saved!/);

    // The dropdown stays open after saving; close it via its backdrop overlay,
    // then change the config and reload the preset.
    await page.locator('div.fixed.inset-0.z-40').last().click({ position: { x: 5, y: 5 } });
    await expect(page.getByText('Parameter Presets')).toBeHidden();
    await stepsInput.fill('12');
    await page.getByTitle('Manage Presets').click();
    await page.getByText(presetName, { exact: true }).click();
    await expectToast(page, new RegExp(`Loaded preset: ${presetName}`));
    await expect(stepsInput).toHaveValue('34');
  });

  test('Advanced: runway panel toggles and Raw JSON compiles to valid JSON', async ({ page }) => {
    await page.goto('/advanced');
    await expect(page.getByRole('heading', { name: 'Advanced Workflow' })).toBeVisible();

    await page.getByTitle('Toggle Settings & Runway').click();
    await expect(page.getByText('Advanced Runway')).toBeVisible();
    await expect(page.getByText(/preflight checks/i)).toBeVisible();
    await page.getByTitle('Toggle Settings & Runway').click();
    await expect(page.getByText('Advanced Runway')).toBeHidden();

    await page.getByRole('button', { name: 'Raw JSON' }).click();
    await expect(page.getByText('WORKFLOW JSON', { exact: true })).toBeVisible();
    const textarea = page.getByPlaceholder('Paste ComfyUI API Format JSON here...');
    const raw = await textarea.inputValue();
    expect(() => JSON.parse(raw)).not.toThrow();

    // Run Workflow is disabled while there is nothing to parse
    await textarea.fill('');
    await expect(page.getByRole('button', { name: /Run Workflow/ })).toBeDisabled();
  });

  test('@fullstack Simple: enhanced generation (Hi-Res + ADetailer + PAG) completes', async ({ page }) => {
    test.setTimeout(JOB_TIMEOUT + 60000);
    const checkpoints = await listModels(page, 'models/checkpoints');
    test.skip(!checkpoints.length, 'no checkpoints installed');

    await page.goto('/generate');
    await selectCheckpoint(page, pickSingleVersionModel(checkpoints));

    const promptText = `${uniqueName('e2e-enhanced')} a brass mech owl perched on a cathedral gargoyle`;
    await page.getByPlaceholder('Describe what you want to create...').fill(promptText);

    await expandEnhancements(page);
    await page.getByLabel('Hi-Res Fix').check();
    await page.getByLabel('ADetailer').check();
    await page.getByPlaceholder('e.g. detailed face, blue eyes').fill('detailed face, sharp eyes');
    await page.getByLabel('PAG (Perturbed Attention Guidance)').check();

    const jobResponse = page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().includes('/api/generate'),
      { timeout: 45000 }
    );
    await visibleGenerate(page).click();

    const job = await (await jobResponse).json();
    created.push({ kind: 'job', id: job.id });

    await expectToast(page, /Image generated!/, JOB_TIMEOUT);
    const done = await waitForJob(page, job.id, { timeout: JOB_TIMEOUT });
    expect(done.outputs?.length).toBeGreaterThan(0);
  });
});