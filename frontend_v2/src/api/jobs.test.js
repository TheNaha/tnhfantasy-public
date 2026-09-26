import { beforeEach, describe, expect, it, vi } from 'vitest';

const getMock = vi.hoisted(() => vi.fn());
const postMock = vi.hoisted(() => vi.fn());
const deleteMock = vi.hoisted(() => vi.fn());

vi.mock('./client', () => ({
    default: {
        get: getMock,
        post: postMock,
        delete: deleteMock,
    },
}));

import jobsApi from './jobs';

describe('jobsApi.acknowledge', () => {
    beforeEach(() => {
        getMock.mockReset();
        postMock.mockReset();
        deleteMock.mockReset();
    });

    it('acknowledges a single job', () => {
        jobsApi.acknowledge('job-1');

        expect(postMock).toHaveBeenCalledWith('/api/jobs/job-1/acknowledge', {
            acknowledged: true,
        });
    });

    it('restores a single job when acknowledged is false', () => {
        jobsApi.acknowledge('job-1', false);

        expect(postMock).toHaveBeenCalledWith('/api/jobs/job-1/acknowledge', {
            acknowledged: false,
        });
    });

    it('acknowledges every failed job by default', () => {
        jobsApi.acknowledgeAll();

        expect(postMock).toHaveBeenCalledWith('/api/jobs/acknowledge-all', {
            acknowledged: true,
            task_type: null,
        });
    });

    it('passes the task type filter through on the bulk endpoint', () => {
        jobsApi.acknowledgeAll({ taskType: 'llm' });

        expect(postMock).toHaveBeenCalledWith('/api/jobs/acknowledge-all', {
            acknowledged: true,
            task_type: 'llm',
        });
    });

    it('restores every failed job when acknowledged is false', () => {
        jobsApi.acknowledgeAll({ acknowledged: false });

        expect(postMock).toHaveBeenCalledWith('/api/jobs/acknowledge-all', {
            acknowledged: false,
            task_type: null,
        });
    });
});

describe('jobsApi.getFailed', () => {
    beforeEach(() => {
        getMock.mockReset();
        postMock.mockReset();
        deleteMock.mockReset();
    });

    it('hides acknowledged failures unless asked for them', () => {
        jobsApi.getFailed({ limit: 5, taskType: null });

        expect(getMock).toHaveBeenCalledWith('/api/jobs/failed', {
            params: { limit: 5 },
        });
    });

    it('asks the backend to include acknowledged failures', () => {
        jobsApi.getFailed({ limit: 5, taskType: 'image', includeAcknowledged: true });

        expect(getMock).toHaveBeenCalledWith('/api/jobs/failed', {
            params: { limit: 5, task_type: 'image', include_acknowledged: true },
        });
    });
});
