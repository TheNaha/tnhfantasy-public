import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock all external dependencies of jobStore
vi.mock('../api/websocket', () => ({
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
    subscribe: vi.fn().mockResolvedValue(undefined),
    unsubscribe: vi.fn(),
    on: vi.fn().mockReturnValue(() => {}),
    cancelJob: vi.fn().mockResolvedValue({ status: 'cancelled' }),
    getConnectionStatus: vi.fn().mockReturnValue(false),
    EventTypes: {
        JOB_CREATED: 'job.created',
        JOB_UPDATED: 'job.updated',
        JOB_PROGRESS: 'job.progress',
        JOB_POST_PROCESSING: 'job.post_processing',
        JOB_COMPLETED: 'job.completed',
        JOB_FAILED: 'job.failed',
        JOB_CANCELLED: 'job.cancelled',
    },
}));

vi.mock('../api', () => ({
    jobsApi: {
        list: vi.fn().mockResolvedValue({ jobs: [] }),
        delete: vi.fn().mockResolvedValue({ success: true }),
        clear: vi.fn().mockResolvedValue({ deleted: 0 }),
    },
}));

describe('useJobStore', () => {
    let useJobStore;
    let jobsApi;
    let wsApi;

    beforeEach(async () => {
        vi.resetModules();
        vi.clearAllMocks();

        // Re-mock after reset
        vi.mock('../api/websocket', () => ({
            connect: vi.fn().mockResolvedValue(undefined),
            disconnect: vi.fn(),
            subscribe: vi.fn().mockResolvedValue(undefined),
            unsubscribe: vi.fn(),
            on: vi.fn().mockReturnValue(() => {}),
            cancelJob: vi.fn().mockResolvedValue({ status: 'cancelled' }),
            getConnectionStatus: vi.fn().mockReturnValue(false),
            EventTypes: {
                JOB_CREATED: 'job.created',
                JOB_UPDATED: 'job.updated',
                JOB_PROGRESS: 'job.progress',
                JOB_POST_PROCESSING: 'job.post_processing',
                JOB_COMPLETED: 'job.completed',
                JOB_FAILED: 'job.failed',
                JOB_CANCELLED: 'job.cancelled',
            },
        }));

        vi.mock('../api', () => ({
            jobsApi: {
                list: vi.fn().mockResolvedValue({ jobs: [] }),
                delete: vi.fn().mockResolvedValue({ success: true }),
                clear: vi.fn().mockResolvedValue({ deleted: 0 }),
            },
        }));

        const mod = await import('../store/jobStore.js');
        useJobStore = mod.useJobStore;
        const apiMod = await import('../api');
        jobsApi = apiMod.jobsApi;
        wsApi = await import('../api/websocket');
    });

    describe('initial state', () => {
        it('starts with empty jobs list', () => {
            const { jobs } = useJobStore.getState();
            expect(jobs).toEqual([]);
        });

        it('starts with empty jobs', () => {
            const { jobs } = useJobStore.getState();
            expect(jobs).toEqual([]);
        });

        it('starts disconnected', () => {
            const { isConnected } = useJobStore.getState();
            expect(isConnected).toBe(false);
        });

        it('starts with no connection error', () => {
            const { connectionError } = useJobStore.getState();
            expect(connectionError).toBeNull();
        });

        it('starts with null lastCompletedJob', () => {
            const { lastCompletedJob } = useJobStore.getState();
            expect(lastCompletedJob).toBeNull();
        });
    });

});
