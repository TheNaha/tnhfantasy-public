import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import FailedJobsPanel from './FailedJobsPanel';

const useJobRecovery = vi.fn();

vi.mock('../../hooks/useJobRecovery', () => ({
    useJobRecovery: (...args) => useJobRecovery(...args),
}));

vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn() },
}));

function makeRecovery(overrides = {}) {
    return {
        jobs: [],
        total: 0,
        summary: null,
        isLoading: false,
        retryJob: vi.fn().mockResolvedValue({}),
        cancelJob: vi.fn().mockResolvedValue({}),
        recoverJobs: vi.fn().mockResolvedValue({ recovered: 0, failed: 0 }),
        isRetrying: false,
        retryingJobId: null,
        isCancelling: false,
        isRecovering: false,
        ...overrides,
    };
}

const FAILED_JOB = {
    id: 'job-1',
    task_type: 'image',
    status: 'failed',
    error: 'All providers failed: p1',
    provider_id: 'modal-p1',
    completed_at: '2026-01-01T12:00:00Z',
    metadata: { prompt: 'a cat', checkpoint: 'dreamshaper.safetensors' },
    diagnostics: {
        provider_id: 'p1',
        last_provider_id: 'p1',
        model: 'dreamshaper.safetensors',
        attempt_count: 2,
        attempts: [
            { provider_id: 'p1', attempt: 1, outcome: 'timeout', error: 'provider hung', duration_seconds: 30 },
            { provider_id: 'p1', attempt: 2, outcome: 'error', error: 'OutOfMemory', duration_seconds: 12 },
        ],
        error_type: 'providers_exhausted',
        error_message: 'All providers failed: p1',
        duration_seconds: 42.5,
        is_stale: false,
        is_retryable: true,
        retry_of: null,
    },
};

function renderPanel() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <FailedJobsPanel />
        </QueryClientProvider>
    );
}

describe('FailedJobsPanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('renders nothing while loading', () => {
        useJobRecovery.mockReturnValue(makeRecovery({ isLoading: true }));
        const { container } = renderPanel();
        expect(container).toBeEmptyDOMElement();
    });

    it('renders nothing when no job failed', () => {
        useJobRecovery.mockReturnValue(makeRecovery());
        const { container } = renderPanel();
        expect(container).toBeEmptyDOMElement();
    });

    it('shows the failure cause, provider, model and attempt count', () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({
                jobs: [FAILED_JOB],
                total: 1,
                summary: { by_error_type: { providers_exhausted: 1 }, retryable: 1 },
            })
        );
        renderPanel();

        expect(screen.getByLabelText('Failed jobs')).toBeInTheDocument();
        expect(screen.getByText('Providers exhausted · 1')).toBeInTheDocument();
        expect(screen.getByText('All providers failed: p1')).toBeInTheDocument();
        expect(screen.getByText('p1')).toBeInTheDocument();
        expect(screen.getByText('dreamshaper')).toBeInTheDocument();
        expect(screen.getByText(/2 attempts/)).toBeInTheDocument();
    });

    it('labels interrupted (stale) failures understandably', () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({
                jobs: [
                    {
                        ...FAILED_JOB,
                        error: 'Server restart during processing - job timed out',
                        diagnostics: {
                            ...FAILED_JOB.diagnostics,
                            error_type: 'stale_recovery',
                            is_stale: true,
                        },
                    },
                ],
                total: 1,
                summary: { by_error_type: { stale_recovery: 1 }, retryable: 1 },
            })
        );
        renderPanel();

        expect(screen.getByText('Interrupted · 1')).toBeInTheDocument();
        expect(
            screen.getByText(/A restart or dead worker left this job running/i)
        ).toBeInTheDocument();
    });

    it('retries a failed job on click', async () => {
        const retryJob = vi.fn().mockResolvedValue({});
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 1, retryJob })
        );
        renderPanel();

        fireEvent.click(screen.getByLabelText('Retry failed job job-1'));

        expect(retryJob).toHaveBeenCalledWith('job-1');
    });

    it('disables retry for jobs the backend marked unretryable', () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({
                jobs: [
                    {
                        ...FAILED_JOB,
                        diagnostics: { ...FAILED_JOB.diagnostics, is_retryable: false },
                    },
                ],
                total: 1,
            })
        );
        renderPanel();

        expect(screen.getByLabelText('Retry failed job job-1')).toBeDisabled();
    });

    it('expands the attempt timeline on demand', async () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 1 })
        );
        renderPanel();

        expect(screen.queryByText('provider hung')).not.toBeInTheDocument();
        fireEvent.click(screen.getByLabelText('Toggle attempt history for job job-1'));
        expect(screen.getByText(/provider hung/)).toBeInTheDocument();
        expect(screen.getByText(/OutOfMemory/)).toBeInTheDocument();
    });

    it('recovers the queue on demand', async () => {
        const recoverJobs = vi.fn().mockResolvedValue({ recovered: 2, failed: 1 });
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 1, recoverJobs })
        );
        renderPanel();

        fireEvent.click(
            screen.getByLabelText('Recover stuck jobs and requeue interrupted work')
        );

        expect(recoverJobs).toHaveBeenCalled();
    });

    it('collapses the job list when the header is toggled', async () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 1 })
        );
        renderPanel();

        expect(screen.getByText('All providers failed: p1')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /failed jobs/i }));
        expect(screen.queryByText('All providers failed: p1')).not.toBeInTheDocument();
    });

    it('shows the total when the page is truncated', async () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 12, summary: null })
        );
        renderPanel();

        await waitFor(() =>
            expect(screen.getByText(/1 of 12/)).toBeInTheDocument()
        );
    });
});
