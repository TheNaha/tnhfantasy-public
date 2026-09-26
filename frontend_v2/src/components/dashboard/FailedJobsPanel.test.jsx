import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import toast from 'react-hot-toast';
import FailedJobsPanel from './FailedJobsPanel';

const useJobRecovery = vi.fn();

vi.mock('../../hooks/useJobRecovery', () => ({
    useJobRecovery: (...args) => useJobRecovery(...args),
}));

vi.mock('react-hot-toast', () => {
    const toast = vi.fn();
    toast.success = vi.fn();
    toast.error = vi.fn();
    toast.dismiss = vi.fn();
    return { default: toast };
});

function makeRecovery(overrides = {}) {
    return {
        jobs: [],
        total: 0,
        summary: null,
        acknowledgedCount: 0,
        isLoading: false,
        retryJob: vi.fn().mockResolvedValue({}),
        cancelJob: vi.fn().mockResolvedValue({}),
        recoverJobs: vi.fn().mockResolvedValue({ recovered: 0, failed: 0 }),
        acknowledgeJob: vi.fn().mockResolvedValue({}),
        unacknowledgeJob: vi.fn().mockResolvedValue({}),
        acknowledgeAll: vi.fn().mockResolvedValue({ acknowledged: true, updated: 1 }),
        unacknowledgeAll: vi.fn().mockResolvedValue({ acknowledged: false, updated: 1 }),
        isRetrying: false,
        retryingJobId: null,
        isCancelling: false,
        isRecovering: false,
        isAcknowledging: false,
        isAcknowledgingAll: false,
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

/** The panel body starts collapsed so failures never fill the first screen. */
function expandPanel() {
    fireEvent.click(screen.getByRole('button', { name: /failed jobs/i }));
}

/** A second job that failed the same way on the same provider. */
function siblingJob(id, durationSeconds) {
    return {
        ...FAILED_JOB,
        id,
        completed_at: '2026-01-01T12:00:05Z',
        error: 'All providers failed: Every provider was tried and failed',
        metadata: { prompt: `a dog, take ${id}`, checkpoint: 'dreamshaper.safetensors' },
        diagnostics: {
            ...FAILED_JOB.diagnostics,
            duration_seconds: durationSeconds,
        },
    };
}

/** The same job, already acknowledged by the user. */
function acknowledgedJob(overrides = {}) {
    return { ...FAILED_JOB, acknowledged_at: '2026-01-01T13:00:00Z', ...overrides };
}

/** Render the body of the last toast, which is where the Undo action lives. */
function renderLastToast() {
    const renderToast = toast.mock.calls.at(-1)[0];
    return render(renderToast({ id: 'dismiss-toast' }));
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
        expandPanel();

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
        expandPanel();

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
        expandPanel();

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
        expandPanel();

        expect(screen.getByLabelText('Retry failed job job-1')).toBeDisabled();
    });

    it('expands the attempt timeline on demand', async () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 1 })
        );
        renderPanel();
        expandPanel();

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

    it('keeps Recover reachable while the panel is collapsed', () => {
        const recoverJobs = vi.fn().mockResolvedValue({ recovered: 0, failed: 0 });
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 1, recoverJobs })
        );
        renderPanel();

        expect(screen.queryByText('All providers failed: p1')).not.toBeInTheDocument();
        fireEvent.click(
            screen.getByLabelText('Recover stuck jobs and requeue interrupted work')
        );

        expect(recoverJobs).toHaveBeenCalled();
    });

    it('expands the job list on demand and collapses it again', async () => {
        useJobRecovery.mockReturnValue(
            makeRecovery({ jobs: [FAILED_JOB], total: 1 })
        );
        renderPanel();

        expect(screen.queryByText('All providers failed: p1')).not.toBeInTheDocument();
        expandPanel();
        expect(screen.getByText('All providers failed: p1')).toBeInTheDocument();
        expandPanel();
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

    describe('grouping', () => {
        it('renders one group for jobs that share a cause, with the right count', () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [FAILED_JOB, siblingJob('job-2', 7), siblingJob('job-3', 8)],
                    total: 3,
                    summary: { by_error_type: { providers_exhausted: 3 }, retryable: 3 },
                })
            );
            renderPanel();
            expandPanel();

            expect(screen.getByText('3 jobs failed — Every provider was tried and failed.')).toBeInTheDocument();
            expect(screen.getAllByText('Providers exhausted')).toHaveLength(1);
        });

        it('renders one group per distinct cause', () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [
                        FAILED_JOB,
                        siblingJob('job-2', 7),
                        {
                            ...FAILED_JOB,
                            id: 'job-3',
                            provider_id: 'llm-local',
                            error: 'The provider did not answer in time.',
                            diagnostics: {
                                ...FAILED_JOB.diagnostics,
                                error_type: 'timeout',
                            },
                        },
                    ],
                    total: 3,
                    summary: { by_error_type: { providers_exhausted: 2, timeout: 1 }, retryable: 3 },
                })
            );
            renderPanel();
            expandPanel();

            expect(screen.getByText(/2 jobs failed/)).toBeInTheDocument();
            expect(screen.getByText(/1 job failed/)).toBeInTheDocument();
            expect(screen.getByText('Timed out')).toBeInTheDocument();
        });

        it('splits the same cause across different providers', () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [
                        FAILED_JOB,
                        { ...FAILED_JOB, id: 'job-2', provider_id: 'modal-p2' },
                    ],
                    total: 2,
                })
            );
            renderPanel();
            expandPanel();

            expect(screen.getAllByText('Providers exhausted')).toHaveLength(2);
            expect(screen.getByText('p1')).toBeInTheDocument();
            expect(screen.getByText('p2')).toBeInTheDocument();
        });

        it('keeps the per-job detail reachable one click away', () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [FAILED_JOB, siblingJob('job-2', 7), siblingJob('job-3', 8)],
                    total: 3,
                })
            );
            renderPanel();
            expandPanel();

            // Grouped away by default: no job card, model or prompt is shown.
            expect(screen.queryByText('All providers failed: p1')).not.toBeInTheDocument();
            expect(screen.queryByText('a cat')).not.toBeInTheDocument();

            fireEvent.click(
                screen.getByLabelText('Show the 3 jobs that failed on p1')
            );

            // Every job is still there, each with its own model, prompt and retry.
            expect(screen.getByLabelText('Retry failed job job-1')).toBeInTheDocument();
            expect(screen.getByLabelText('Retry failed job job-2')).toBeInTheDocument();
            expect(screen.getByLabelText('Retry failed job job-3')).toBeInTheDocument();
            expect(screen.getByText('a cat')).toBeInTheDocument();
            expect(screen.getByText('a dog, take job-2')).toBeInTheDocument();
        });

        it('retries a grouped job individually without changing retry behaviour', () => {
            const retryJob = vi.fn().mockResolvedValue({});
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [FAILED_JOB, siblingJob('job-2', 7)],
                    total: 2,
                    retryJob,
                })
            );
            renderPanel();
            expandPanel();
            fireEvent.click(screen.getByLabelText('Show the 2 jobs that failed on p1'));
            fireEvent.click(screen.getByLabelText('Retry failed job job-2'));

            expect(retryJob).toHaveBeenCalledTimes(1);
            expect(retryJob).toHaveBeenCalledWith('job-2');
        });

        it('caps the expanded list height so it cannot fill the screen', () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({ jobs: [FAILED_JOB, siblingJob('job-2', 7)], total: 2 })
            );
            renderPanel();
            expandPanel();

            const list = screen.getByText(/2 jobs failed/).closest('div.px-5');
            expect(list.className).toContain('overflow-y-auto');
            expect(list.className).toContain('max-h-[40vh]');
        });
    });

    describe('dismissal', () => {
        it('renders one dismiss control per failure group, named for its cause', () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [
                        FAILED_JOB,
                        siblingJob('job-2', 7),
                        {
                            ...FAILED_JOB,
                            id: 'job-3',
                            provider_id: 'llm-local',
                            diagnostics: { ...FAILED_JOB.diagnostics, error_type: 'timeout' },
                        },
                    ],
                    total: 3,
                })
            );
            renderPanel();
            expandPanel();

            expect(
                screen.getByLabelText(
                    'Dismiss the 2 jobs that failed on p1 without retrying them'
                )
            ).toBeInTheDocument();
            expect(
                screen.getByLabelText(
                    'Dismiss the 1 job that failed on llm-local without retrying it'
                )
            ).toBeInTheDocument();
        });

        it('acknowledges every job in the dismissed group and nothing else', async () => {
            const acknowledgeJob = vi.fn().mockResolvedValue({});
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [
                        FAILED_JOB,
                        siblingJob('job-2', 7),
                        {
                            ...FAILED_JOB,
                            id: 'job-3',
                            provider_id: 'llm-local',
                            diagnostics: { ...FAILED_JOB.diagnostics, error_type: 'timeout' },
                        },
                    ],
                    total: 3,
                    acknowledgeJob,
                })
            );
            renderPanel();
            expandPanel();

            fireEvent.click(
                screen.getByLabelText('Dismiss the 2 jobs that failed on p1 without retrying them')
            );

            await waitFor(() => expect(acknowledgeJob).toHaveBeenCalledTimes(2));
            expect(acknowledgeJob.mock.calls.map((call) => call[0])).toEqual(['job-1', 'job-2']);
        });

        it('undo on the dismiss toast restores exactly the dismissed jobs', async () => {
            const unacknowledgeJob = vi.fn().mockResolvedValue({});
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [FAILED_JOB, siblingJob('job-2', 7)],
                    total: 2,
                    unacknowledgeJob,
                })
            );
            renderPanel();
            expandPanel();

            fireEvent.click(
                screen.getByLabelText('Dismiss the 2 jobs that failed on p1 without retrying them')
            );

            await waitFor(() => expect(toast).toHaveBeenCalled());
            renderLastToast();
            expect(screen.getByText('Dismissed 2 failures')).toBeInTheDocument();

            fireEvent.click(screen.getByRole('button', { name: 'Undo' }));

            await waitFor(() => expect(unacknowledgeJob).toHaveBeenCalledTimes(2));
            expect(unacknowledgeJob.mock.calls.map((call) => call[0])).toEqual(['job-1', 'job-2']);
            expect(toast.dismiss).toHaveBeenCalledWith('dismiss-toast');
        });

        it('reports a failed dismiss instead of claiming success', async () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [FAILED_JOB],
                    total: 1,
                    acknowledgeJob: vi.fn().mockRejectedValue(new Error('Job is not failed')),
                })
            );
            renderPanel();
            expandPanel();

            fireEvent.click(
                screen.getByLabelText('Dismiss the 1 job that failed on p1 without retrying it')
            );

            await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Job is not failed'));
            expect(toast).not.toHaveBeenCalled();
        });

        it('dismisses everything from the header without retrying anything', async () => {
            const acknowledgeAll = vi.fn().mockResolvedValue({ acknowledged: true, updated: 7 });
            const retryJob = vi.fn().mockResolvedValue({});
            useJobRecovery.mockReturnValue(
                makeRecovery({ jobs: [FAILED_JOB], total: 7, acknowledgeAll, retryJob })
            );
            renderPanel();

            // Reachable while collapsed, next to Recover, and not a retry.
            fireEvent.click(
                screen.getByLabelText('Dismiss all failures without retrying them')
            );

            await waitFor(() => expect(acknowledgeAll).toHaveBeenCalled());
            expect(retryJob).not.toHaveBeenCalled();
            await waitFor(() => expect(toast).toHaveBeenCalled());
            renderLastToast();
            expect(screen.getByText('Dismissed 7 failures')).toBeInTheDocument();
        });

        it('undo on dismiss-all restores every failure', async () => {
            const unacknowledgeAll = vi.fn().mockResolvedValue({ acknowledged: false, updated: 7 });
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [FAILED_JOB],
                    total: 7,
                    acknowledgeAll: vi.fn().mockResolvedValue({ acknowledged: true, updated: 7 }),
                    unacknowledgeAll,
                })
            );
            renderPanel();

            fireEvent.click(
                screen.getByLabelText('Dismiss all failures without retrying them')
            );

            await waitFor(() => expect(toast).toHaveBeenCalled());
            renderLastToast();
            fireEvent.click(screen.getByRole('button', { name: 'Undo' }));

            await waitFor(() => expect(unacknowledgeAll).toHaveBeenCalled());
        });

        it('renders nothing when the only failures left are acknowledged', () => {
            useJobRecovery.mockReturnValue(makeRecovery({ jobs: [], total: 0 }));
            const { container } = renderPanel();

            // The default query hides acknowledged jobs, so an all-dismissed
            // history leaves the panel with nothing to render.
            expect(container).toBeEmptyDOMElement();
            expect(useJobRecovery).toHaveBeenCalledWith({ limit: 5, includeAcknowledged: false });
        });

        it('refetches with acknowledged failures only once the toggle is on', async () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({ jobs: [FAILED_JOB], total: 1, acknowledgedCount: 3 })
            );
            renderPanel();

            // Quiet while there is nothing to bring back, counted when there is.
            const toggle = screen.getByRole('button', { name: 'Show acknowledged (3)' });
            expect(toggle).toHaveAttribute('aria-pressed', 'false');
            fireEvent.click(toggle);

            expect(useJobRecovery).toHaveBeenLastCalledWith({
                limit: 5,
                includeAcknowledged: true,
            });
        });

        it('counts the acknowledged failures once they are shown', async () => {
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [FAILED_JOB, acknowledgedJob({ id: 'job-2' })],
                    total: 2,
                })
            );
            renderPanel();

            fireEvent.click(screen.getByRole('button', { name: 'Show acknowledged' }));

            const toggle = screen.getByRole('button', { name: 'Hide acknowledged (1)' });
            expect(toggle).toHaveAttribute('aria-pressed', 'true');
        });

        it('marks an acknowledged group and offers to show it again', async () => {
            const unacknowledgeJob = vi.fn().mockResolvedValue({});
            useJobRecovery.mockReturnValue(
                makeRecovery({
                    jobs: [acknowledgedJob()],
                    total: 1,
                    unacknowledgeJob,
                })
            );
            renderPanel();
            expandPanel();

            expect(screen.getByText('Acknowledged')).toBeInTheDocument();
            fireEvent.click(
                screen.getByLabelText('Show the dismissed 1 job from p1 again')
            );

            await waitFor(() =>
                expect(unacknowledgeJob).toHaveBeenCalledWith('job-1')
            );
        });
    });
});

describe('FailedJobsPanel — fully dismissed', () => {
    it('keeps a way back when every failure is dismissed', () => {
        // Rendering nothing once the last failure is dismissed removed the only
        // re-entry point, because the "show acknowledged" toggle lives inside the
        // panel. The 6s undo toast is not a durable way back.
        useJobRecovery.mockReturnValue(makeRecovery({ jobs: [], acknowledgedCount: 3 }));

        render(<FailedJobsPanel />);

        expect(screen.getByText(/3 dismissed failures/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /show dismissed/i })).toBeInTheDocument();
    });

    it('renders nothing when there is nothing to show and nothing to restore', () => {
        useJobRecovery.mockReturnValue(makeRecovery({ jobs: [], acknowledgedCount: 0 }));

        const { container } = render(<FailedJobsPanel />);

        expect(container).toBeEmptyDOMElement();
    });
});
