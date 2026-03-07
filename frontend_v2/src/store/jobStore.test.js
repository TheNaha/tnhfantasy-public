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
    });

    describe('initial state', () => {
        it('starts with empty jobs list', () => {
            const { jobs } = useJobStore.getState();
            expect(jobs).toEqual([]);
        });

        it('starts with empty activeJobs', () => {
            const { activeJobs } = useJobStore.getState();
            expect(activeJobs).toEqual([]);
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

    describe('setJobs', () => {
        it('keeps only active jobs and sorts by created_at descending', () => {
            const { setJobs } = useJobStore.getState();
            const jobs = [
                { id: 'a', status: 'completed', created_at: '2024-01-01T00:00:00Z' },
                { id: 'b', status: 'running', created_at: '2024-01-03T00:00:00Z' },
                { id: 'c', status: 'pending', created_at: '2024-01-02T00:00:00Z' },
            ];
            setJobs(jobs);
            const state = useJobStore.getState();
            expect(state.jobs[0].id).toBe('b'); // Most recent first
            expect(state.jobs[1].id).toBe('c');
            expect(state.jobs.length).toBe(2);
        });

        it('computes activeJobs from pending/running jobs', () => {
            const { setJobs } = useJobStore.getState();
            setJobs([
                { id: 'a', status: 'completed', created_at: '2024-01-01T00:00:00Z' },
                { id: 'b', status: 'pending', created_at: '2024-01-02T00:00:00Z' },
                { id: 'c', status: 'running', created_at: '2024-01-03T00:00:00Z' },
                { id: 'd', status: 'failed', created_at: '2024-01-04T00:00:00Z' },
            ]);
            const { activeJobs } = useJobStore.getState();
            expect(activeJobs.length).toBe(2);
            const activeIds = activeJobs.map(j => j.id);
            expect(activeIds).toContain('b');
            expect(activeIds).toContain('c');
        });

        it('includes queued, processing, executing as active', () => {
            const { setJobs } = useJobStore.getState();
            setJobs([
                { id: 'a', status: 'queued', created_at: '2024-01-01T00:00:00Z' },
                { id: 'b', status: 'processing', created_at: '2024-01-02T00:00:00Z' },
                { id: 'c', status: 'executing', created_at: '2024-01-03T00:00:00Z' },
            ]);
            const { activeJobs } = useJobStore.getState();
            expect(activeJobs.length).toBe(3);
        });

        it('merges existing jobs with incoming (server data takes precedence)', () => {
            const { setJobs } = useJobStore.getState();
            // Set initial jobs
            setJobs([{ id: 'a', status: 'pending', created_at: '2024-01-01T00:00:00Z', extra: 'keep' }]);
            // Update with server data (should merge)
            setJobs([{ id: 'a', status: 'running', created_at: '2024-01-01T00:00:00Z' }]);
            const { jobs } = useJobStore.getState();
            const jobA = jobs.find(j => j.id === 'a');
            expect(jobA.status).toBe('running');
        });

        it('deduplicates jobs with same id', () => {
            const { setJobs } = useJobStore.getState();
            setJobs([
                { id: 'a', status: 'pending', created_at: '2024-01-01T00:00:00Z' },
                { id: 'a', status: 'running', created_at: '2024-01-01T00:00:00Z' },
            ]);
            expect(useJobStore.getState().jobs.length).toBe(1);
        });
    });

    describe('updateJob', () => {
        it('updates an existing job by id', () => {
            const { setJobs, updateJob } = useJobStore.getState();
            setJobs([{ id: 'a', status: 'pending', progress: 0, created_at: '2024-01-01T00:00:00Z' }]);
            updateJob('a', { progress: 50 });
            const job = useJobStore.getState().jobs.find(j => j.id === 'a');
            expect(job.progress).toBe(50);
            expect(job.status).toBe('pending'); // Other fields unchanged
        });

        it('does not affect other jobs', () => {
            const { setJobs, updateJob } = useJobStore.getState();
            setJobs([
                { id: 'a', status: 'pending', created_at: '2024-01-01T00:00:00Z' },
                { id: 'b', status: 'running', created_at: '2024-01-02T00:00:00Z' },
            ]);
            updateJob('a', { status: 'completed' });
            const jobB = useJobStore.getState().jobs.find(j => j.id === 'b');
            expect(jobB.status).toBe('running');
        });
    });

    describe('_processMessage', () => {
        it('handles job.created event by adding new job', () => {
            const { _processMessage } = useJobStore.getState();
            _processMessage({
                type: 'job.created',
                data: { job: { id: 'new-job', status: 'pending', created_at: '2024-01-01T00:00:00Z' } }
            });
            const { jobs } = useJobStore.getState();
            expect(jobs.some(j => j.id === 'new-job')).toBe(true);
        });

        it('handles job.created event by updating if job already exists', () => {
            const { setJobs, _processMessage } = useJobStore.getState();
            setJobs([{ id: 'existing', status: 'pending', created_at: '2024-01-01T00:00:00Z' }]);
            _processMessage({
                type: 'job.created',
                data: { job: { id: 'existing', status: 'running', created_at: '2024-01-01T00:00:00Z' } }
            });
            const job = useJobStore.getState().jobs.find(j => j.id === 'existing');
            expect(job.status).toBe('running');
        });

        it('handles job.progress event by updating job', () => {
            const { setJobs, _processMessage } = useJobStore.getState();
            setJobs([{ id: 'job1', status: 'running', progress: 0, created_at: '2024-01-01T00:00:00Z' }]);
            _processMessage({
                type: 'job.progress',
                data: { job: { id: 'job1', status: 'running', progress: 75 } }
            });
            const job = useJobStore.getState().jobs.find(j => j.id === 'job1');
            expect(job.progress).toBe(75);
        });

        it('handles job.completed event by removing from activeJobs', () => {
            const { setJobs, _processMessage } = useJobStore.getState();
            setJobs([{ id: 'job1', status: 'running', created_at: '2024-01-01T00:00:00Z' }]);
            _processMessage({
                type: 'job.completed',
                data: { job: { id: 'job1', status: 'completed' } }
            });
            const { activeJobs } = useJobStore.getState();
            expect(activeJobs.some(j => j.id === 'job1')).toBe(false);
        });

        it('sets lastCompletedJob on job.completed event', () => {
            const { setJobs, _processMessage } = useJobStore.getState();
            setJobs([{ id: 'job1', status: 'running', created_at: '2024-01-01T00:00:00Z' }]);
            _processMessage({
                type: 'job.completed',
                data: { job: { id: 'job1', status: 'completed', outputs: ['image.png'] } }
            });
            const { lastCompletedJob } = useJobStore.getState();
            expect(lastCompletedJob).not.toBeNull();
            expect(lastCompletedJob.id).toBe('job1');
        });

        it('handles job.failed event by removing from activeJobs', () => {
            const { setJobs, _processMessage } = useJobStore.getState();
            setJobs([{ id: 'job1', status: 'running', created_at: '2024-01-01T00:00:00Z' }]);
            _processMessage({
                type: 'job.failed',
                data: { job: { id: 'job1', status: 'failed', error: 'timeout' } }
            });
            const { activeJobs } = useJobStore.getState();
            expect(activeJobs.some(j => j.id === 'job1')).toBe(false);
        });

        it('handles legacy V1 job_update message', () => {
            const { setJobs, _processMessage } = useJobStore.getState();
            setJobs([{ id: 'job1', status: 'pending', progress: 0, created_at: '2024-01-01T00:00:00Z' }]);
            _processMessage({
                type: 'job_update',
                job: { id: 'job1', status: 'running', progress: 30 }
            });
            const job = useJobStore.getState().jobs.find(j => j.id === 'job1');
            expect(job.progress).toBe(30);
        });
    });

    describe('fetchJobs', () => {
        it('calls jobsApi.list and populates jobs', async () => {
            const mockJobs = [
                { id: 'a', status: 'completed', created_at: '2024-01-01T00:00:00Z' },
                { id: 'b', status: 'running', created_at: '2024-01-02T00:00:00Z' }
            ];
            jobsApi.list.mockResolvedValueOnce({ jobs: mockJobs });

            const { fetchJobs } = useJobStore.getState();
            await fetchJobs();
            expect(useJobStore.getState().jobs.length).toBe(1);
            expect(useJobStore.getState().jobs[0].id).toBe('b');
        });

        it('throws on API error', async () => {
            jobsApi.list.mockRejectedValueOnce(new Error('network error'));
            const { fetchJobs } = useJobStore.getState();
            await expect(fetchJobs()).rejects.toThrow('network error');
        });
    });

    describe('deleteJob', () => {
        it('optimistically removes the job immediately', async () => {
            const { setJobs, deleteJob } = useJobStore.getState();
            setJobs([
                { id: 'del-me', status: 'running', created_at: '2024-01-01T00:00:00Z' },
                { id: 'keep', status: 'pending', created_at: '2024-01-02T00:00:00Z' },
            ]);
            const deletePromise = deleteJob('del-me');
            // Optimistic: job should be removed immediately
            expect(useJobStore.getState().jobs.some(j => j.id === 'del-me')).toBe(false);
            await deletePromise;
        });

        it('rolls back on API error', async () => {
            const { setJobs, deleteJob } = useJobStore.getState();
            setJobs([{ id: 'del-me', status: 'running', created_at: '2024-01-01T00:00:00Z' }]);
            jobsApi.delete.mockRejectedValueOnce(new Error('server error'));
            await expect(deleteJob('del-me')).rejects.toThrow();
            // Job should be restored after rollback
            expect(useJobStore.getState().jobs).toEqual([
                expect.objectContaining({ id: 'del-me', status: 'running' }),
            ]);
            expect(useJobStore.getState().activeJobs).toEqual([
                expect.objectContaining({ id: 'del-me', status: 'running' }),
            ]);
        });
    });

    describe('clearJobs', () => {
        it('optimistically clears all jobs immediately', async () => {
            const { setJobs, clearJobs } = useJobStore.getState();
            setJobs([
                { id: 'a', status: 'running', created_at: '2024-01-01T00:00:00Z' },
                { id: 'b', status: 'pending', created_at: '2024-01-02T00:00:00Z' },
            ]);
            const clearPromise = clearJobs();
            // Optimistic: cleared immediately
            expect(useJobStore.getState().jobs).toEqual([]);
            await clearPromise;
        });

        it('rolls back on API error', async () => {
            const { setJobs, clearJobs } = useJobStore.getState();
            setJobs([
                { id: 'a', status: 'running', created_at: '2024-01-01T00:00:00Z' },
            ]);
            jobsApi.clear.mockRejectedValueOnce(new Error('server error'));
            await expect(clearJobs()).rejects.toThrow();
            // Jobs should be restored
            expect(useJobStore.getState().jobs).toEqual([
                expect.objectContaining({ id: 'a', status: 'running' }),
            ]);
            expect(useJobStore.getState().activeJobs).toEqual([
                expect.objectContaining({ id: 'a', status: 'running' }),
            ]);
        });
    });

    describe('createJobOptimistic', () => {
        it('adds a temporary optimistic job before API call resolves', async () => {
            let resolveCreate;
            const createPromise = new Promise(resolve => { resolveCreate = resolve; });
            const generateFn = vi.fn().mockReturnValue(createPromise);

            const { createJobOptimistic } = useJobStore.getState();
            const pendingPromise = createJobOptimistic({}, {}, generateFn);

            // Optimistic job should be added immediately
            const { jobs } = useJobStore.getState();
            const tempJob = jobs.find(j => j.isOptimistic);
            expect(tempJob).toBeDefined();
            expect(tempJob.status).toBe('submitting');

            // Resolve with a real job
            resolveCreate({ id: 'real-job-id', status: 'pending' });
            await pendingPromise;

            // Temp job replaced by real job
            const { jobs: finalJobs } = useJobStore.getState();
            expect(finalJobs.some(j => j.id === 'real-job-id')).toBe(true);
            expect(finalJobs.some(j => j.isOptimistic)).toBe(false);
        });

        it('removes temp job on failure', async () => {
            const generateFn = vi.fn().mockRejectedValue(new Error('failed'));
            const { createJobOptimistic } = useJobStore.getState();
            await expect(createJobOptimistic({}, {}, generateFn)).rejects.toThrow();
            const { jobs } = useJobStore.getState();
            expect(jobs.some(j => j.isOptimistic)).toBe(false);
        });
    });
});
