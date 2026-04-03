import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
const putMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());
const patchMock = vi.hoisted(() => vi.fn());
const deleteMock = vi.hoisted(() => vi.fn());

vi.mock('./client', () => ({
    default: {
        get: getMock,
        put: putMock,
        post: postMock,
        patch: patchMock,
        delete: deleteMock,
    },
}));

import providersApi from './providers';

describe('providersApi load balancer aliases', () => {
    beforeEach(() => {
        getMock.mockReset();
        putMock.mockReset();
        postMock.mockReset();
        patchMock.mockReset();
        deleteMock.mockReset();
    });

    it('uses the canonical config endpoint for getLoadBalancing', () => {
        providersApi.getLoadBalancing();

        expect(getMock).toHaveBeenCalledWith('/api/providers/config/load-balancing');
    });

    it('keeps getLoadBalancerConfig as an alias of getLoadBalancing', () => {
        providersApi.getLoadBalancerConfig();

        expect(getMock).toHaveBeenCalledWith('/api/providers/config/load-balancing');
    });

    it('uses the canonical config endpoint for updateLoadBalancing', () => {
        const payload = { strategy: 'least-connections' };
        providersApi.updateLoadBalancing(payload);

        expect(putMock).toHaveBeenCalledWith('/api/providers/config/load-balancing', payload);
    });

    it('keeps updateLoadBalancerConfig as an alias of updateLoadBalancing', () => {
        const payload = { strategy: 'round-robin' };
        providersApi.updateLoadBalancerConfig(payload);

        expect(putMock).toHaveBeenCalledWith('/api/providers/config/load-balancing', payload);
    });

    it('keeps getStatus as an alias of getStatusCard', () => {
        providersApi.getStatus('modal-primary');

        expect(getMock).toHaveBeenCalledWith('/api/providers/modal-primary/status-card');
    });
});
