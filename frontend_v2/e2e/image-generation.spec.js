import { test, expect } from '@playwright/test';
import {
  apiGet,
  uniqueName,
  expectToast,
  waitForJob,
  makeTestImage,
  seedPrompt,
  seedCollection,
  cleanupEntities,
  drawMaskOnCanvas,
} from './fixtures.js';

const JOB_TIMEOUT = 360000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function listModels(page, directory) {
  const data = await apiGet(page, `/files?directory=${directory}&limit=100`);
  return data.files || [];
}

// Pick a model that is actually usable: skip partial-download artifacts and
// prefer models installed on at least one provider; single-version models
// select in one click.
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

// Select a model card inside the selector dialog. Multi-version cards expand
// first, so click the first version row if the dialog is still open.
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

// GenerateButtonBar renders twice (desktop + mobile) — scope to the visible one.
function visibleGenerate(page) {
  return page.getByRole('button', { name: 'Generate', exact: true }).filter({ visible: true });
}

async function uploadSourceImage(page, filename, rgb) {
  await page.locator('input[type="file"]').first().setInputFiles({
    name: filename,
    mimeType: 'image/png',
    buffer: makeTestImage({ width: 256, height: 256, rgb }),
  });
  await expectToast(page, /Image uploaded/);
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe('Image Generation & Asset Management (Module A)', () => {
  test.setTimeout(240000);

  const created = [];
  test.afterEach(async ({ page }) => {
    await cleanupEntities(page, created.splice(0));
  });

  test('Simple: Generate disabled without a prompt, enabled when filled', async ({ page }) => {
    await page.goto('/generate');
    const prompt = page.getByPlaceholder('Describe what you want to create...');
    const genBtn = visibleGenerate(page);

    await prompt.fill('');
    await expect(genBtn).toBeDisabled();
    await prompt.fill('a test prompt');
    await expect(genBtn).toBeEnabled();
  });

  test('Simple: aspect ratio presets apply and locked dimensions auto-scale', async ({ page }) => {
    await page.goto('/generate');
    const widthInput = page.locator('#width-input');
    const heightInput = page.locator('#height-input');

    await page.getByRole('button', { name: 'Set aspect ratio 16:9, 1344x768 pixels' }).click();
    await expect(widthInput).toHaveValue('1344');
    await expect(heightInput).toHaveValue('768');

    await page.getByRole('button', { name: 'Lock Aspect Ratio' }).click();
    await widthInput.fill('672');
    await expect(heightInput).toHaveValue('384');
    await page.getByRole('button', { name: 'Unlock Aspect Ratio' }).click();
  });

  test('Simple: randomize seed changes the seed value', async ({ page }) => {
    await page.goto('/generate');
    const dice = page.getByTitle('Randomize seed');
    const seedInput = dice.locator('..').locator('input[type="number"]');
    const before = await seedInput.inputValue();
    await dice.click();
    const after = await seedInput.inputValue();
    expect(after).not.toBe(before);
  });

  test('Simple: Magic Prompt enriches or fails gracefully', async ({ page }) => {
    await page.goto('/generate');
    await page.getByLabel('Magic Prompt').click();
    await expectToast(page, /Prompt enriched!|Failed to enrich prompt/);
  });

  test('Simple: prompt library applies a saved prompt', async ({ page }) => {
    const promptEntity = await seedPrompt(page, {
      name: uniqueName('e2e-lib'),
      prompt: 'A misty harbor at dawn, watercolor style',
    });
    created.push({ kind: 'prompt', id: promptEntity.id });

    await page.goto('/generate');
    await page.getByLabel('Open prompt library').click();
    await page.getByPlaceholder('Search prompts...').fill(promptEntity.name);
    await page.getByRole('button', { name: 'Use Prompt' }).click();
    await expectToast(page, /Applied/);
    const positive = page.getByPlaceholder('Describe what you want to create...');
    await expect(positive).toHaveValue(/misty harbor/);
  });

  test('Simple: checkpoint can be selected from the model picker', async ({ page }) => {
    const checkpoints = await listModels(page, 'models/checkpoints');
    test.skip(!checkpoints.length, 'no checkpoints installed');

    await page.goto('/generate');
    await page.getByRole('button', { name: 'Select Checkpoint / UNET' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const model = pickSingleVersionModel(checkpoints);
    await selectModelFromDialog(dialog, model);

    const trigger = page.getByRole('button', { name: 'Select Checkpoint / UNET' });
    await expect(trigger).toContainText(model.display_name || model.name);
  });

  test('Simple: LoRA can be added via auto-open picker and removed', async ({ page }) => {
    const loras = await listModels(page, 'models/loras');
    test.skip(!loras.length, 'no loras installed');

    await page.goto('/generate');
    await page.getByRole('button', { name: 'Add LoRA' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const model = pickSingleVersionModel(loras);
    await selectModelFromDialog(dialog, model);

    await expect(page.getByTitle('Remove')).toBeVisible();
    await expect(page.getByTitle('View info')).toBeVisible();
    await page.getByTitle('Remove').click();
    await expect(page.getByTitle('Remove')).toBeHidden();
  });

  test('Simple: ControlNet card can be added, configured, and removed', async ({ page }) => {
    const cnModels = await listModels(page, 'models/controlnet');
    test.skip(!cnModels.length, 'no controlnet models installed');

    await page.goto('/generate');
    await page.getByRole('button', { name: /ControlNet/ }).click();

    await page.getByRole('button', { name: 'Add ControlNet' }).click();
    const card = page.locator('[class*="group/card"]').first();
    await expect(card).toBeVisible();

    await card.locator('select').nth(0).selectOption(cnModels[0].name);
    await card.locator('select').nth(1).selectOption('Canny Edge');

    await card.locator('input[type="file"]').setInputFiles({
      name: 'cn-image.png',
      mimeType: 'image/png',
      buffer: makeTestImage({ width: 128, height: 128, rgb: [200, 80, 40] }),
    });
    await expectToast(page, /Image uploaded!/);
    await expect(card.getByText(/Uploaded: cn-image.png/)).toBeVisible();

    await card.locator('button').first().click();
    await expect(card).toBeHidden();
  });

  test('Simple: enhancement toggles reveal and hide their sub-controls', async ({ page }) => {
    await page.goto('/generate');
    await page.getByRole('button', { name: /Enhancements/ }).click();

    // max-h-0 wrappers still report elements as "visible" to Playwright, so
    // assert the wrapper class instead of child visibility.
    const subControlState = (label) =>
      page.getByText(label, { exact: true }).locator('..').locator('..');

    await expect(subControlState('Upscaler')).toHaveClass(/pointer-events-none/);
    await expect(subControlState('PAG Scale')).toHaveClass(/pointer-events-none/);
    await expect(subControlState('Scale Multiplier')).toHaveClass(/pointer-events-none/);

    await page.getByLabel('Hi-Res Fix').check();
    await expect(subControlState('Upscaler')).not.toHaveClass(/pointer-events-none/);
    await page.getByLabel('ADetailer').check();
    await expect(page.getByPlaceholder('e.g. detailed face, blue eyes')).toBeVisible();
    await page.getByLabel('FreeU (v2)').check();
    await page.getByLabel('PAG (Perturbed Attention Guidance)').check();
    await expect(subControlState('PAG Scale')).not.toHaveClass(/pointer-events-none/);
    await page.getByLabel('Latent Upscale').check();
    await expect(subControlState('Scale Multiplier')).not.toHaveClass(/pointer-events-none/);

    await page.getByLabel('Hi-Res Fix').uncheck();
    await expect(subControlState('Upscaler')).toHaveClass(/pointer-events-none/);
  });

  test('@fullstack Simple: full Text2Img generation completes end-to-end', async ({ page }) => {
    test.setTimeout(JOB_TIMEOUT + 60000);
    const checkpoints = await listModels(page, 'models/checkpoints');
    test.skip(!checkpoints.length, 'no checkpoints installed');

    await page.goto('/generate');
    await selectCheckpoint(page, pickSingleVersionModel(checkpoints));

    const promptText = `${uniqueName('e2e-gen')} a small red fox in a snowy forest`;
    await page.getByPlaceholder('Describe what you want to create...').fill(promptText);

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

  test('@fullstack Simple: Generate Variations queues 2x and both complete', async ({ page }) => {
    test.setTimeout(JOB_TIMEOUT + 60000);
    const checkpoints = await listModels(page, 'models/checkpoints');
    test.skip(!checkpoints.length, 'no checkpoints installed');

    await page.goto('/generate');
    await selectCheckpoint(page, pickSingleVersionModel(checkpoints));
    await page.getByPlaceholder('Describe what you want to create...').fill('variations test scene, glowing crystals');

    const jobs = [];
    page.on('response', (r) => {
      if (r.request().method() === 'POST' && r.url().includes('/api/generate')) {
        jobs.push(r.json());
      }
    });

    await page.getByTitle('Generate Variations').filter({ visible: true }).click();
    await page.getByRole('button', { name: 'Generate 2x' }).click();
    await expectToast(page, /Queued 2 variations!/);

    await expect
      .poll(async () => jobs.length, { timeout: 45000 })
      .toBe(2);
    const jobIds = (await Promise.all(jobs)).map((j) => j.id);
    created.push(...jobIds.map((id) => ({ kind: 'job', id })));

    for (const id of jobIds) {
      const done = await waitForJob(page, id, { timeout: JOB_TIMEOUT });
      expect(done.outputs?.length).toBeGreaterThan(0);
    }
  });

  test('Img2Img: disabled until source image and checkpoint are set', async ({ page }) => {
    await page.goto('/img2img');
    const genBtn = page.getByRole('button', { name: 'Generate Img2Img' });

    await expect(genBtn).toBeDisabled();
    await uploadSourceImage(page, 'e2e-src.png', [120, 60, 200]);
    await expect(genBtn).toBeDisabled();

    const checkpoints = await listModels(page, 'models/checkpoints');
    if (checkpoints.length) {
      await selectCheckpoint(page, pickSingleVersionModel(checkpoints), 'Checkpoint');
      await expect(genBtn).toBeEnabled();
    }
  });

  test('@fullstack Img2Img: full generation completes end-to-end', async ({ page }) => {
    test.setTimeout(JOB_TIMEOUT + 60000);
    const checkpoints = await listModels(page, 'models/checkpoints');
    test.skip(!checkpoints.length, 'no checkpoints installed');

    await page.goto('/img2img');
    await uploadSourceImage(page, 'e2e-src2.png', [60, 180, 120]);
    await selectCheckpoint(page, pickSingleVersionModel(checkpoints), 'Checkpoint');
    await page.getByPlaceholder('Describe what you want to create...').fill('oil painting, vivid brush strokes');

    const jobResponse = page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().includes('/api/generate'),
      { timeout: 45000 }
    );
    await page.getByRole('button', { name: 'Generate Img2Img' }).click();

    const job = await (await jobResponse).json();
    created.push({ kind: 'job', id: job.id });

    await expectToast(page, /Image generated!/, JOB_TIMEOUT);
    const done = await waitForJob(page, job.id, { timeout: JOB_TIMEOUT });
    expect(done.outputs?.length).toBeGreaterThan(0);
  });

  test('Inpaint: mask canvas tools draw, undo, redo, and clear', async ({ page }) => {
    await page.goto('/inpaint');
    await uploadSourceImage(page, 'e2e-mask.png', [140, 140, 60]);

    const canvas = page.locator('canvas').nth(1);
    await expect(canvas).toBeVisible();
    await expect(page.getByText('Draw a mask on the image to continue')).toBeVisible();

    const brush = page.getByLabel('Brush tool (paint mask)');
    const eraser = page.getByLabel('Eraser tool (remove mask)');
    const undo = page.getByLabel('Undo mask change');
    const redo = page.getByLabel('Redo mask change');

    await expect(brush).toHaveAttribute('aria-pressed', 'true');
    await expect(undo).toBeDisabled();
    await expect(redo).toBeDisabled();

    await drawMaskOnCanvas(canvas, { from: { x: 0.3, y: 0.3 }, to: { x: 0.7, y: 0.7 } });
    await expect(undo).toBeEnabled();
    await expect(page.getByText('Draw a mask on the image to continue')).toBeHidden();

    await undo.click();
    await expect(undo).toBeDisabled();
    await expect(redo).toBeEnabled();

    await eraser.click();
    await expect(eraser).toHaveAttribute('aria-pressed', 'true');
    await brush.click();
    await expect(brush).toHaveAttribute('aria-pressed', 'true');

    await drawMaskOnCanvas(canvas, { from: { x: 0.1, y: 0.1 }, to: { x: 0.2, y: 0.2 } });
    await page.getByLabel('Clear mask').click();
    await expect(page.getByText('Draw a mask on the image to continue')).toBeVisible();
    await expect(redo).toBeDisabled();
    await expect(undo).toBeEnabled();
  });

  test('@fullstack Inpaint: full generation completes end-to-end', async ({ page }) => {
    test.setTimeout(JOB_TIMEOUT + 60000);
    const checkpoints = await listModels(page, 'models/checkpoints');
    test.skip(!checkpoints.length, 'no checkpoints installed');

    await page.goto('/inpaint');
    await uploadSourceImage(page, 'e2e-mask2.png', [90, 90, 200]);

    const canvas = page.locator('canvas').nth(1);
    await drawMaskOnCanvas(canvas, { from: { x: 0.4, y: 0.4 }, to: { x: 0.6, y: 0.6 } });
    await selectCheckpoint(page, pickSingleVersionModel(checkpoints), 'Checkpoint');
    await page.getByPlaceholder('Describe what you want to create...').fill('a glowing lantern');

    const jobResponse = page.waitForResponse(
      (r) => r.request().method() === 'POST' && r.url().includes('/api/generate'),
      { timeout: 45000 }
    );
    await page.getByRole('button', { name: 'Generate Inpaint' }).click();

    const job = await (await jobResponse).json();
    created.push({ kind: 'job', id: job.id });

    await expectToast(page, /Image generated!/, JOB_TIMEOUT);
    const done = await waitForJob(page, job.id, { timeout: JOB_TIMEOUT });
    expect(done.outputs?.length).toBeGreaterThan(0);
  });

  test('Advanced: invalid JSON shows an error toast', async ({ page }) => {
    await page.goto('/advanced');
    await page.getByRole('button', { name: 'Raw JSON' }).click();
    await page.getByPlaceholder('Paste ComfyUI API Format JSON here...').fill('{not valid json');
    await page.getByRole('button', { name: 'Run Workflow' }).click();
    await expectToast(page, /Invalid JSON/);
  });

  test('Advanced: visual graph exposes runway and node search', async ({ page }) => {
    await page.goto('/advanced');
    await page.getByRole('button', { name: 'Visual Graph' }).click();
    await page.getByTitle('Toggle Settings & Runway').click();
    await expect(page.getByText('Advanced Runway')).toBeVisible();

    const nodeSearch = page.getByPlaceholder('Search nodes...');
    await expect(nodeSearch).toBeVisible();
    await nodeSearch.fill('KSampler');
    const result = page.getByText('No nodes found').or(page.locator('[draggable="true"]').first());
    await expect(result).toBeVisible();
  });

  test('Gallery: lightbox opens and Reuse Parameters fills the generator', async ({ page }) => {
    await page.goto('/');
    const firstCard = page.locator('[role="img"]').first();
    await firstCard.waitFor({ state: 'visible', timeout: 30000 });

    await firstCard.click();
    await expect(page.getByLabel('Close lightbox')).toBeVisible();

    const reuse = page.getByRole('button', { name: 'Reuse Parameters' });
    if (!(await reuse.isVisible({ timeout: 3000 }).catch(() => false))) {
      test.skip(true, 'image has no metadata to reuse');
    }
    await reuse.click();
    await expect(page).toHaveURL(/\/generate$/);
    const prompt = page.getByPlaceholder('Describe what you want to create...');
    expect((await prompt.inputValue()).length).toBeGreaterThan(0);
  });

  test('Gallery: favorite toggle on a card, then restored', async ({ page }) => {
    await page.goto('/');
    const firstCard = page.locator('[role="img"]').first();
    await firstCard.waitFor({ state: 'visible', timeout: 30000 });

    const star = firstCard.getByRole('button', { name: /Add to favorites|Remove from favorites/ });
    await star.click();
    await expectToast(page, /Added to favorites|Removed from favorites/);
    await star.click();
    await expectToast(page, /Added to favorites|Removed from favorites/);
  });

  test('Gallery: selection mode adds images to a collection', async ({ page }) => {
    const collection = await seedCollection(page, { name: uniqueName('e2e-col'), workspace: 'main' });
    created.push({ kind: 'collection', id: collection.id });

    await page.goto('/');
    const firstCard = page.locator('[role="img"]').first();
    await firstCard.waitFor({ state: 'visible', timeout: 30000 });

    await page.keyboard.press('s');
    await expect(page.getByText('0 selected')).toBeVisible({ timeout: 5000 });
    await firstCard.click();
    await expect(page.getByText('1 selected')).toBeVisible();

    await page.getByRole('button', { name: 'Add to Collection' }).click();
    await page.getByLabel(`Select collection ${collection.name}`).click();
    await expectToast(page, /Added 1 images to collection/);

    const updated = await apiGet(page, `/collections/${collection.id}?include_images=true`);
    expect(updated.images?.length ?? updated.image_count).toBeGreaterThan(0);
  });
});
