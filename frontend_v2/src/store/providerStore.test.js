import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
    providersApi: {
        getLoadBalancerConfig: vi.fn().mockResolvedValue({
            config: { strategy: 'round-robin', fallback_enabled: true },
            stats: { total_providers: 1, provider_stats: [{ id: 'provider-1', failures: 0, jobs_assigned: 0 }] },
        }),
        startContainer: vi.fn().mockResolvedValue({ success: true }),
        stopContainer: vi.fn().mockResolvedValue({ success: true }),
        restartContainer: vi.fn().mockResolvedValue({ success: true }),
        deploy: vi.fn().mockResolvedValue({ provider_type: 'modal' }),
        reconcile: vi.fn().mockResolvedValue({ started: true }),
        setup: vi.fn().mockResolvedValue({ message: 'Setup complete' }),
        resetModelStatus: vi.fn().mockResolvedValue({ deleted_count: 2 }),
        update: vi.fn().mockResolvedValue({ success: true }),
        delete: vi.fn().mockResolvedValue({ success: true }),
        updateLoadBalancerConfig: vi.fn().mockResolvedValue({ success: true }),
        create: vi.fn().mockResolvedValue({ id: 'provider-2' }),
    },
}));

describe('useProviderStore', () => {
    let useProviderStore;
    let providersApi;

    beforeEach(async () => {
        vi.resetModules();
        vi.clearAllMocks();

        const storeMod = await import('../store/providerStore.js');
        useProviderStore = storeMod.useProviderStore;
        const apiMod = await import('../api');
        providersApi = apiMod.providersApi;

        useProviderStore.setState({
            containerLoading: {},
        });
    });

    it('startContainer updates loading state around API call', async () => {
        const promise = useProviderStore.getState().startContainer('provider-1');

        expect(useProviderStore.getState().containerLoading['provider-1']).toBe('starting');

        await promise;

        expect(providersApi.startContainer).toHaveBeenCalledWith('provider-1');
        expect(useProviderStore.getState().containerLoading['provider-1']).toBeNull();
    });

    it('reconcileProvider tracks loading state', async () => {
        const promise = useProviderStore.getState().reconcileProvider('provider-1');

        expect(useProviderStore.getState().containerLoading['provider-1']).toBe('reconciling');

        await promise;

        expect(providersApi.reconcile).toHaveBeenCalledWith('provider-1');
        expect(useProviderStore.getState().containerLoading['provider-1']).toBeNull();
    });

    it('setupProvider and resetProviderModelStatus call provider APIs', async () => {
        await useProviderStore.getState().setupProvider('provider-1');
        await useProviderStore.getState().resetProviderModelStatus('provider-1');

        expect(providersApi.setup).toHaveBeenCalledWith('provider-1');
        expect(providersApi.resetModelStatus).toHaveBeenCalledWith('provider-1');
    });

    it('toggleProviderEnabled updates enabled flag only', async () => {
        await useProviderStore.getState().toggleProviderEnabled('provider-1', true);

        expect(providersApi.update).toHaveBeenCalledWith('provider-1', { enabled: false });
    });

    it('updateLoadBalancerStrategy uses provided config when available', async () => {
        await useProviderStore.getState().updateLoadBalancerStrategy('least-connections', {
            strategy: 'round-robin',
            fallback_enabled: true,
        });

        expect(providersApi.getLoadBalancerConfig).not.toHaveBeenCalled();
        expect(providersApi.updateLoadBalancerConfig).toHaveBeenCalledWith({
            strategy: 'least-connections',
            fallback_enabled: true,
        });
    });

    it('updateLoadBalancerStrategy falls back to API config when missing', async () => {
        await useProviderStore.getState().updateLoadBalancerStrategy('priority');

        expect(providersApi.getLoadBalancerConfig).toHaveBeenCalled();
        expect(providersApi.updateLoadBalancerConfig).toHaveBeenCalledWith({
            strategy: 'priority',
            fallback_enabled: true,
        });
    });

    it('saveProvider creates or updates providers', async () => {
        await useProviderStore.getState().saveProvider(null, { id: 'provider-2', type: 'modal' });
        await useProviderStore.getState().saveProvider({ id: 'provider-1' }, { enabled: false });

        expect(providersApi.create).toHaveBeenCalledWith({ id: 'provider-2', type: 'modal' });
        expect(providersApi.update).toHaveBeenCalledWith('provider-1', { enabled: false });
    });
});
