import { test, expect } from '@playwright/test';
import {
    apiGet,
    apiPost,
    apiPut,
    apiDelete,
    uniqueName,
    expectToast,
    providerCard,
    seedProvider,
    fetchProvider,
    cleanupProvider,
} from './fixtures.js';

// ---------------------------------------------------------------------------
// Provider Management (Module E) — strict rewrite.
//
// Every test seeds its own throwaway provider via the API and deletes it via
// the API when done, so the real stack (modal-zetsuke, modal-stepmania,
// direct-url, llm-local) is never mutated. Throwaway providers are created
// DISABLED so they can never receive dispatched jobs (useProvidersPageData
// feeds them the requirement that only enabled providers are candidates).
//
// The one exception is the Ping test, which targets the real `modal-zetsuke`
// container from docker-compose.dev.yml — the same provider the @fullstack
// suite bills jobs to.
// ---------------------------------------------------------------------------

const STRATEGY_LABELS = {
    'round-robin': 'Round Robin',
    'random': 'Random',
    'priority': 'Priority',
    'least-connections': 'Least Conn.',
    'priority-round-robin': 'Priority + RR',
    'priority-least-connections': 'Priority + LC',
};

test.describe('Provider Management (Module E)', () => {
    test.setTimeout(90000);

    test('Strict smoke: heading, count and Cleanup action', async ({ page }) => {
        await page.goto('/providers');

        await expect(page.getByRole('heading', { name: /providers/i })).toBeVisible({ timeout: 10000 });
        await expect(page.getByText(/providers configured/i)).toBeVisible();

        await page.getByRole('button', { name: 'Cleanup', exact: true }).click();
        await expectToast(page, /Cleanup: \d+ orphaned removed, \d+ stale reset/);
    });

    test('Add Provider via modal persists with correct fields (API-verified)', async ({ page }) => {
        const id = uniqueName('e2e-px');
        await page.goto('/providers');

        await page.getByRole('button', { name: 'Add Provider', exact: true }).click();
        await expect(page.getByRole('heading', { name: 'Add Provider', exact: true })).toBeVisible();

        await page.getByLabel('Provider ID').fill(id);
        await page.getByLabel('Type').selectOption('llm-local');
        await page.getByRole('checkbox', { name: /route jobs to this provider/i }).uncheck();
        await page.getByLabel('Priority').fill('5');
        await page.getByLabel('API Endpoint URL').fill('http://127.0.0.1:9');

        await page.getByRole('button', { name: 'Create Provider', exact: true }).click();
        await expectToast(page, /Provider created/);
        await expect(page.getByRole('heading', { name: 'Add Provider', exact: true })).toBeHidden();

        const created = await fetchProvider(page, id);
        expect(created).not.toBeNull();
        expect(created.type).toBe('llm-local');
        expect(created.worker_type).toBe('llm');
        expect(created.enabled).toBe(false);
        expect(created.priority).toBe(5);

        await cleanupProvider(page, id);
    });

    test('Required Provider ID blocks creation', async ({ page }) => {
        await page.goto('/providers');

        await page.getByRole('button', { name: 'Add Provider', exact: true }).click();
        await expect(page.getByRole('heading', { name: 'Add Provider', exact: true })).toBeVisible();

        await page.getByRole('button', { name: 'Create Provider', exact: true }).click();
        await expect(page.getByRole('heading', { name: 'Add Provider', exact: true })).toBeVisible();

        await page.getByRole('button', { name: 'Cancel', exact: true }).click();
        await expect(page.getByRole('heading', { name: 'Add Provider', exact: true })).toBeHidden();
    });

    test('Edit provider: redacted banner, locked ID, priority persists (API-verified)', async ({ page }) => {
        const id = uniqueName('e2e-px');
        await seedProvider(page, id);
        await page.goto('/providers');

        const card = providerCard(page, id);
        await expect(card).toBeVisible();
        await card.getByRole('button', { name: 'Edit Provider', exact: true }).click();

        await expect(page.getByRole('heading', { name: 'Edit Provider', exact: true })).toBeVisible();
        await expect(page.getByText(/existing credentials are redacted/i)).toBeVisible();
        await expect(page.getByLabel('Provider ID')).toBeDisabled();

        await page.getByLabel('Priority').fill('3');
        await page.getByRole('button', { name: 'Save Changes', exact: true }).click();
        await expectToast(page, /Provider updated/);

        const updated = await fetchProvider(page, id);
        expect(updated.priority).toBe(3);

        await cleanupProvider(page, id);
    });

    test('Enable/Disable toggle round-trips through the API', async ({ page }) => {
        const id = uniqueName('e2e-px');
        await seedProvider(page, id, { enabled: false });
        await page.goto('/providers');

        const card = providerCard(page, id);
        await expect(card).toBeVisible();

        await card.getByRole('button', { name: 'Enable Provider', exact: true }).click();
        await expect.poll(async () => (await fetchProvider(page, id)).enabled).toBe(true);
        await expect(card.getByRole('button', { name: 'Enable Provider', exact: true })).toHaveCount(0);
        await expect(card.getByRole('button', { name: 'Disable Provider', exact: true })).toBeVisible();

        await card.getByRole('button', { name: 'Disable Provider', exact: true }).click();
        await expect.poll(async () => (await fetchProvider(page, id)).enabled).toBe(false);
        await expect(card.getByRole('button', { name: 'Enable Provider', exact: true })).toBeVisible();

        await cleanupProvider(page, id);
    });

    test('Delete provider from the list (UI + API verified)', async ({ page }) => {
        const id = uniqueName('e2e-px');
        await seedProvider(page, id);
        await page.goto('/providers');

        const card = providerCard(page, id);
        await expect(card).toBeVisible();

        await card.getByRole('button', { name: 'Delete Provider', exact: true }).click();
        await expectToast(page, /Provider deleted/);
        await expect(providerCard(page, id)).toHaveCount(0);

        await expect.poll(async () => (await fetchProvider(page, id))).toBeNull();
    });

    test('Detail drawer: LLM providers hide Deploy/Model Sync tabs', async ({ page }) => {
        const id = uniqueName('e2e-px');
        await seedProvider(page, id);
        await page.goto('/providers');

        await providerCard(page, id).click();

        // Drawer header only (the card subtitle says "LLM provider", the drawer says "<type> provider").
        await expect(page.getByText('llm-local provider', { exact: true })).toBeVisible();
        await expect(page.getByText(/runtime status/i)).toBeVisible();

        // Tab bar: Service tabs present, Deploy + Model Sync filtered out for LLM workers.
        for (const tab of ['Active Jobs', 'Diagnostics', 'Live Console']) {
            await expect(page.getByRole('button', { name: tab, exact: true })).toBeVisible();
        }
        await expect(page.getByRole('button', { name: 'Deploy', exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: 'Model Sync', exact: true })).toHaveCount(0);

        await page.getByRole('button', { name: 'Active Jobs', exact: true }).click();
        await expect(page.getByText('No active jobs running on this provider.')).toBeVisible();

        await page.getByRole('button', { name: 'Live Console', exact: true }).click();
        await expect(page.getByText('Console Logs', { exact: true })).toBeVisible();
        await expect(page.getByText(/no logs available/i)).toBeVisible({ timeout: 15000 });

        await page.getByRole('button', { name: 'Diagnostics', exact: true }).click();
        await expect(page.getByText('Live Remote Metrics', { exact: true })).toBeVisible();
        await expect(page.getByText('Credential Ready', { exact: true })).toBeVisible();

        // Close button returns to the list.
        await page.getByRole('button', { name: 'Close', exact: true }).click();
        await expect(page.getByText('llm-local provider', { exact: true })).toHaveCount(0);

        await cleanupProvider(page, id);
    });

    test('Test Connection reports unreachable LLM worker as an error', async ({ page }) => {
        const id = uniqueName('e2e-px');
        await seedProvider(page, id);
        await page.goto('/providers');

        await providerCard(page, id).click();
        await expect(page.getByRole('button', { name: 'Test Connection', exact: true })).toBeVisible();

        await page.getByRole('button', { name: 'Test Connection', exact: true }).click();
        await expect(page.getByText(/Error: .+/)).toBeVisible({ timeout: 25000 });

        await cleanupProvider(page, id);
    });

    test('Send Ping Test reaches the real modal worker container', async ({ page }) => {
        await page.goto('/providers');

        // tnhcomfy-modal-zetsuke is the enabled Modal provider from docker-compose.dev.yml.
        await providerCard(page, 'modal-zetsuke').click();
        await expect(page.getByRole('button', { name: 'Send Ping Test', exact: true })).toBeVisible();

        await page.getByRole('button', { name: 'Send Ping Test', exact: true }).click();
        await expect(page.getByText(/Success \(\d+ms\)/)).toBeVisible({ timeout: 15000 });
    });

    test('Load-balancer strategy change persists and is restored', async ({ page }) => {
        const lb = await apiGet(page, '/providers/config/load-balancing');
        const original = lb.config.strategy;
        const target = original === 'random' ? 'priority' : 'random';
        const targetLabel = STRATEGY_LABELS[target];
        const originalLabel = STRATEGY_LABELS[original];

        await page.goto('/providers');

        const bar = page.getByRole('button', { name: /Load Balancer/ });
        await expect(bar).toBeVisible();

        try {
            await bar.click();
            await page.getByRole('button', { name: targetLabel, exact: true }).click();

            await expect.poll(async () => {
                const config = await apiGet(page, '/providers/config/load-balancing');
                return config.config.strategy;
            }, { timeout: 15000 }).toBe(target);

            await expect(page.getByRole('button', { name: new RegExp(`Load Balancer[\\s\\S]*${targetLabel}`) })).toBeVisible({ timeout: 10000 });
        } finally {
            await apiPut(page, '/providers/config/load-balancing', { strategy: original });
            await expect.poll(async () => {
                const config = await apiGet(page, '/providers/config/load-balancing');
                return config.config.strategy;
            }).toBe(original);
            await page.reload();
            await expect(page.getByRole('button', { name: new RegExp(`Load Balancer[\\s\\S]*${originalLabel}`) })).toBeVisible({ timeout: 10000 });
        }
    });
});