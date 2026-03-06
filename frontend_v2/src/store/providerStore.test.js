import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/websocket', () => ({
    connect: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn().mockResolvedValue(undefined),
    unsubscribe: vi.fn(),
    on: vi.fn().mockReturnValue(() => {}),
    EventTypes: {
        PROVIDER_CONTAINER_STATUS: 'provider.container_status',
        PROVIDER_STATS_UPDATE: 'provider.stats_update',
    },
}));

vi.mock('../api', () => ({
    providersApi: {
        list: vi.fn().mockResolvedValue([{ id: 'provider-1', enabled: true }]),
        getAllContainerStatuses: vi.fn().mockResolvedValue({
            statuses: { 'provider-1': { status: 'running', running: true, healthy: true } },
        }),
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
            providers: [],
            containerStatuses: {},
            lbConfig: null,
            lbStats: null,
            isLoading: false,
            containerLoading: {},
            _wsInitialized: false,
            _unsubscribers: [],
        });
    });

    it('fetchProviders populates provider state', async () => {
        await useProviderStore.getState().fetchProviders();

        expect(useProviderStore.getState().providers).toEqual([{ id: 'provider-1', enabled: true }]);
    });

    it('startContainer updates loading state and refreshes statuses', async () => {
        const promise = useProviderStore.getState().startContainer('provider-1');

        expect(useProviderStore.getState().containerLoading['provider-1']).toBe('starting');

        await promise;

        expect(providersApi.startContainer).toHaveBeenCalledWith('provider-1');
        expect(providersApi.getAllContainerStatuses).toHaveBeenCalled();
        expect(useProviderStore.getState().containerLoading['provider-1']).toBeNull();
        expect(useProviderStore.getState().containerStatuses['provider-1'].healthy).toBe(true);
    });

    it('toggleProviderEnabled refreshes providers and load balancer info', async () => {
        await useProviderStore.getState().toggleProviderEnabled('provider-1', true);

        expect(providersApi.update).toHaveBeenCalledWith('provider-1', { enabled: false });
        expect(providersApi.list).toHaveBeenCalled();
        expect(providersApi.getLoadBalancerConfig).toHaveBeenCalled();
    });

    it('saveProvider creates and refreshes state for new providers', async () => {
        await useProviderStore.getState().saveProvider(null, { id: 'provider-2', type: 'modal' });

        expect(providersApi.create).toHaveBeenCalledWith({ id: 'provider-2', type: 'modal' });
        expect(providersApi.list).toHaveBeenCalled();
        expect(providersApi.getAllContainerStatuses).toHaveBeenCalled();
        expect(providersApi.getLoadBalancerConfig).toHaveBeenCalled();
    });

    it('refreshAll fetches providers, statuses, and load balancer info together', async () => {
        await useProviderStore.getState().refreshAll();

        expect(providersApi.list).toHaveBeenCalled();
        expect(providersApi.getAllContainerStatuses).toHaveBeenCalled();
        expect(providersApi.getLoadBalancerConfig).toHaveBeenCalled();
    });

    it('reconcileProvider tracks loading state', async () => {
        const promise = useProviderStore.getState().reconcileProvider('provider-1');

        expect(useProviderStore.getState().containerLoading['provider-1']).toBe('reconciling');

        await promise;

        expect(providersApi.reconcile).toHaveBeenCalledWith('provider-1');
        expect(useProviderStore.getState().containerLoading['provider-1']).toBeNull();
    });

    it('setupProvider and resetProviderModelStatus use provider APIs', async () => {
        await useProviderStore.getState().setupProvider('provider-1');
        await useProviderStore.getState().resetProviderModelStatus('provider-1');

        expect(providersApi.setup).toHaveBeenCalledWith('provider-1');
        expect(providersApi.resetModelStatus).toHaveBeenCalledWith('provider-1');
    });
});