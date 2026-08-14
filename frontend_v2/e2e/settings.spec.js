import { test, expect } from '@playwright/test';
import { apiGet, apiPost, apiPut, expectToast, uniqueName } from './fixtures.js';

// LocalStorage key used by the Zustand persist middleware.
const LS_KEY = 'comfyui-settings-storage';

// Tab label -> heading shown when the tab is active.
const TABS = [
    ['AI / LLM', 'AI / LLM Settings'],
    ['Branding', 'Branding'],
    ['UI / UX', 'UI / UX Settings'],
    ['Gallery', 'Gallery Settings'],
    ['Models', 'Model Manager Settings'],
    ['Generator', 'Generator Settings'],
];

async function openTab(page, label) {
    await page.getByRole('button', { name: label, exact: true }).click();
}

// SettingGroup renders title+description in a flex-1 column and the control in a
// `shrink-0` sibling column: title -> flex-1 -> parent root -> shrink-0 child.
function groupControl(page, title) {
    return page
        .getByText(title, { exact: true })
        .locator('xpath=ancestor::div[contains(@class,"flex-1")][1]')
        .locator('xpath=parent::div/div[contains(@class,"shrink-0")]');
}
function groupSlider(page, title) {
    return groupControl(page, title).locator('input[type="range"]');
}
// Value badge next to a slider, or the Enabled/Disabled label of a toggle.
function groupBadge(page, title) {
    return groupControl(page, title).locator('span').last();
}

// Read persisted settings straight from localStorage.
async function readPersistedSettings(page) {
    return page.evaluate(async (key) => {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw).state.settings : null;
    }, LS_KEY);
}

test.describe('Settings & Configuration (Module F)', () => {
    test.setTimeout(60000);

    test('All 6 tabs render and each shows its section heading', async ({ page }) => {
        await page.goto('/settings');
        await expect(page.getByRole('heading', { level: 1, name: 'Settings' })).toBeVisible();

        for (const [label, heading] of TABS) {
            const tabBtn = page.getByRole('button', { name: label, exact: true });
            await expect(tabBtn).toBeVisible();
            await tabBtn.click();
            await expect(page.getByRole('heading', { level: 2, name: heading })).toBeVisible();
        }
    });

    test('UI: grid columns slider updates badge and localStorage', async ({ page }) => {
        await page.goto('/settings');
        await openTab(page, 'UI / UX');

        const slider = groupSlider(page, 'Default Grid Columns');
        await slider.fill('6');
        await expectToast(page, /Setting updated!/);
        await expect(groupBadge(page, 'Default Grid Columns')).toHaveText('6');

        const persisted = await readPersistedSettings(page);
        expect(persisted.ui.defaultGridColumns).toBe(6);
    });

    test('UI: toast test buttons fire success and error toasts', async ({ page }) => {
        await page.goto('/settings');
        await openTab(page, 'UI / UX');

        const successTest = page
            .getByText('Toast Success Duration', { exact: true })
            .locator('xpath=ancestor::div[contains(@class,"flex-1")][1]')
            .getByRole('button', { name: 'Test', exact: true });
        await successTest.click();
        await expectToast(page, /Test toast \(\d+ms duration\)/);

        const errorTest = page
            .getByText('Toast Error Duration', { exact: true })
            .locator('xpath=ancestor::div[contains(@class,"flex-1")][1]')
            .getByRole('button', { name: 'Test', exact: true });
        await errorTest.click();
        await expectToast(page, /Test error toast \(\d+ms duration\)/);
    });

    test('UI: category reset restores defaults', async ({ page }) => {
        await page.goto('/settings');
        await openTab(page, 'UI / UX');

        const slider = groupSlider(page, 'Default Grid Columns');
        await slider.fill('6');
        await expect(groupBadge(page, 'Default Grid Columns')).toHaveText('6');

        await page.getByRole('button', { name: 'Reset', exact: true }).click();
        await expectToast(page, /UI settings reset to defaults/);
        await expect(groupBadge(page, 'Default Grid Columns')).toHaveText('4');
    });

    test('Gallery: both toggles flip and persist to localStorage', async ({ page }) => {
        await page.goto('/settings');
        await openTab(page, 'Gallery');

        for (const title of ['Auto-Refresh on Job Complete', 'Silent Refresh']) {
            const label = groupControl(page, title).locator('label').first();
            const badge = groupBadge(page, title);
            const before = await badge.textContent();
            await label.click();
            await expect(badge).not.toHaveText(before);
        }

        const persisted = await readPersistedSettings(page);
        expect(typeof persisted.gallery.autoRefreshOnJobComplete).toBe('boolean');
        expect(typeof persisted.gallery.silentRefresh).toBe('boolean');
    });

    test('Branding: save applies app name to the sidebar, then restores', async ({ page }) => {
        const original = await apiGet(page, '/settings/branding');
        const brand = uniqueName('e2e-brand');

        await page.goto('/settings');
        await openTab(page, 'Branding');
        await page.getByPlaceholder('Enter app name').fill(brand);
        await page.getByRole('button', { name: 'Save', exact: true }).click();
        await expectToast(page, /Branding updated! Refresh the page to see changes./);

        const saved = await apiGet(page, '/settings/branding');
        expect(saved.appName).toBe(brand);

        await page.goto('/');
        await expect(page.getByText(brand).filter({ visible: true }).first()).toBeVisible();

        await apiPost(page, '/settings/branding', original);
    });

    test('AI: LLM worker status reflects enabled providers', async ({ page }) => {
        const providers = await apiGet(page, '/v2/llm/providers');
        const enabled = providers.filter((p) => p.enabled);

        await page.goto('/settings');
        await openTab(page, 'AI / LLM');

        await expect(page.getByText('LLM Worker Status', { exact: true })).toBeVisible();
        await expect(page.getByText(/Connected|Unavailable/).first()).toBeVisible();
        await expect(page.getByText(`Enabled Providers (${enabled.length})`)).toBeVisible();

        for (const p of enabled) {
            await expect(page.getByText(p.provider_id, { exact: true }).first()).toBeVisible();
        }
    });

    test('AI: default LLM provider save flow updates backend, then restores', async ({ page }) => {
        let original = null;
        try {
            original = await apiGet(page, '/v2/llm/default-provider');
        } catch {
            original = null; // 404: no default configured yet
        }

        const providers = await apiGet(page, '/v2/llm/providers');
        const llmProviders = providers.filter((p) => p.worker_type === 'llm' || (p.provider_id || p.id || '').startsWith('llm'));
        const target = llmProviders.find((p) => (p.provider_id || p.id) === 'llm-local') ?? llmProviders[0];
        expect(target, 'an enabled LLM provider must exist on this stack').toBeTruthy();

        await page.goto('/settings');
        await openTab(page, 'AI / LLM');

        const card = page.getByText('Default LLM Provider', { exact: true }).locator('xpath=ancestor::div[contains(@class,"p-6")][1]');
        const targetId = target.provider_id || target.id;
        await card.getByRole('combobox').first().selectOption(targetId);
        await card.getByRole('button', { name: 'Save', exact: true }).click();
        await expectToast(page, /Default LLM provider updated/);

        const saved = await apiGet(page, '/v2/llm/default-provider');
        expect(saved.provider_id).toBe(targetId);

        if (original) {
            await apiPut(page, '/v2/llm/default-provider', {
                provider_id: original.provider_id,
                model_id: original.model_id,
            });
        }
    });

    test('AI: context tokens + temperature save to backend config, then restore', async ({ page }) => {
        const settings = await apiGet(page, '/settings');
        const originalAi = settings.settings.ai || { maxContextTokens: 4096, temperature: 0.8 };

        await page.goto('/settings');
        await openTab(page, 'AI / LLM');

        await groupSlider(page, 'Max Context Tokens').fill('8192');
        await groupSlider(page, 'Temperature').fill('1.2');
        await expect(groupBadge(page, 'Max Context Tokens')).toHaveText('8192');
        await expect(groupBadge(page, 'Temperature')).toHaveText('1.2');

        const saveBtn = page
            .getByText('AI / LLM Settings', { exact: true })
            .locator('xpath=ancestor::div[1]')
            .getByRole('button', { name: 'Save', exact: true });
        await saveBtn.click();
        await expectToast(page, /AI settings saved to backend/);
        await expect(page.getByRole('button', { name: 'Saved', exact: true })).toBeVisible();

        const saved = await apiGet(page, '/settings');
        expect(saved.settings.ai.maxContextTokens).toBe(8192);
        expect(saved.settings.ai.temperature).toBe(1.2);

        await apiPut(page, '/settings', { ai: originalAi });
    });

    test('Generator: redirect toggle reveals/hides the delay setting', async ({ page }) => {
        await page.goto('/settings');
        await openTab(page, 'Generator');

        const redirect = groupControl(page, 'Redirect After Generate').locator('label').first();
        const delayTitle = page.getByText('Redirect Delay', { exact: true });

        const initiallyOn = await groupBadge(page, 'Redirect After Generate').textContent() === 'Enabled';
        if (initiallyOn) {
            await expect(delayTitle).toBeVisible();
        }
        await redirect.click();
        await expectToast(page, /Setting updated!/);
        await expect(delayTitle).toBeHidden();

        await redirect.click();
        await expect(delayTitle).toBeVisible();

        const persisted = await readPersistedSettings(page);
        expect(persisted.generator.redirectAfterGenerate).toBe(true);
    });

    test('Models: items per page and auto-remove toggle persist', async ({ page }) => {
        await page.goto('/settings');
        await openTab(page, 'Models');

        await groupSlider(page, 'Items Per Page').fill('50');
        await expect(groupBadge(page, 'Items Per Page')).toHaveText('50');

        const label = groupControl(page, 'Auto-Remove Downloads').locator('label').first();
        const badge = groupBadge(page, 'Auto-Remove Downloads');
        const before = await badge.textContent();
        await label.click();
        await expect(badge).not.toHaveText(before);

        const persisted = await readPersistedSettings(page);
        expect(persisted.models.itemsPerPage).toBe(50);
        expect(typeof persisted.models.autoRemoveDownloads).toBe('boolean');
    });

    test('Reset All (danger confirm) restores defaults', async ({ page }) => {
        await page.goto('/settings');
        await openTab(page, 'UI / UX');
        await groupSlider(page, 'Default Grid Columns').fill('6');
        await expect(groupBadge(page, 'Default Grid Columns')).toHaveText('6');

        await page.getByRole('button', { name: 'Reset All', exact: true }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog.getByText('Reset All Settings', { exact: true })).toBeVisible();
        await dialog.getByRole('button', { name: 'Reset All', exact: true }).click();
        await expectToast(page, /All settings reset to defaults/);

        await expect(groupBadge(page, 'Default Grid Columns')).toHaveText('4');
    });

    test('System prompt blocks: edit, persist to backend, restore', async ({ page }) => {
        const originalBlocks = await apiGet(page, '/settings/system-prompts').then((r) => r.blocks);
        const marker = uniqueName('sys-prompt-e2e');

        await page.goto('/settings');
        await openTab(page, 'AI / LLM');

        await expect(page.getByText('System Prompt Blocks', { exact: true })).toBeVisible();
        const roleplayTa = page
            .getByText('Roleplay Default', { exact: true })
            .locator('xpath=following-sibling::textarea');
        await roleplayTa.fill(marker);
        await page.getByRole('button', { name: /Save prompts/i }).click();
        await expectToast(page, /System prompts updated/);

        const savedBlocks = await apiGet(page, '/settings/system-prompts').then((r) => r.blocks);
        expect(savedBlocks.roleplay_default).toContain(marker);

        await apiPut(page, '/settings/system-prompts', { blocks: originalBlocks });
    });
});