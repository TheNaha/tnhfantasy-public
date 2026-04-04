import { describe, expect, it } from 'vitest';
import { summarizeProviderStatus } from './providerStatus';

function buildProvider(overrides = {}) {
    return {
        id: 'modal-primary',
        enabled: true,
        runtime_state: { status: 'running', connected: true },
        deploy_state: { status: 'idle', message: '' },
        reconciliation_state: { status: 'idle', message: '', active_downloads: [], stats: {} },
        model_sync: { stats: { downloading: 0, pending: 0 } },
        diagnostics: { warnings: [], errors: [] },
        ...overrides,
    };
}

describe('summarizeProviderStatus', () => {
    it('prioritizes deploying state with deploy message', () => {
        const summary = summarizeProviderStatus(buildProvider({
            deploy_state: { status: 'deploying', message: 'Deployment started' },
        }));

        expect(summary.stage).toBe('deploying');
        expect(summary.label).toBe('Deploying');
        expect(summary.message).toBe('Deployment started');
        expect(summary.dotTone).toBe('deploying');
    });

    it('reports syncing and active downloads from reconciliation state', () => {
        const summary = summarizeProviderStatus(buildProvider({
            reconciliation_state: {
                status: 'reconciling',
                message: 'Syncing provider',
                active_downloads: [{ name: 'a' }, { name: 'b' }],
                stats: { downloads_queued: 5 },
            },
            model_sync: { stats: { downloading: 1, pending: 3 } },
        }));

        expect(summary.stage).toBe('syncing');
        expect(summary.downloadsActive).toBe(2);
        expect(summary.downloadsQueued).toBe(5);
        expect(summary.dotTone).toBe('syncing');
    });

    it('returns disabled state before other statuses', () => {
        const summary = summarizeProviderStatus(buildProvider({
            enabled: false,
            deploy_state: { status: 'deploying', message: 'ignore me' },
        }));

        expect(summary.stage).toBe('disabled');
        expect(summary.label).toBe('Disabled');
        expect(summary.message).toBe('Provider disabled');
    });
});
