import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import BackgroundTasks from './BackgroundTasks';
import { settingsApi } from '../api/settingsApi';
import { api } from '../api';

vi.mock('../api/settingsApi', () => ({
    settingsApi: {
        getSchedulerStatus: vi.fn(),
        runSchedulerJob: vi.fn(),
        updateSchedulerJob: vi.fn(),
    },
}));

vi.mock('../api', () => ({
    api: {
        post: vi.fn(),
    },
}));

vi.mock('../api/websocket', () => ({
    on: vi.fn(),
    off: vi.fn(),
}));

const mockSchedulerData = {
    jobs: [
        {
            id: 'civitai_resync_random',
            name: 'civitai_resync_random',
            title: 'Random Batch Metadata Resync',
            description: 'Rapid incremental refresh of metadata for randomized batches of installed models.',
            category: 'Models',
            next_run: '2026-11-09T02:00:00Z',
            paused: false,
            trigger: 'interval[0:05:00]',
            interval_seconds: 300,
            last_run_at: '2026-11-09T01:55:00Z',
            last_status: 'success',
            last_duration_seconds: 1.25,
            last_error: null,
        },
        {
            id: 'civitai_resync_job',
            name: 'civitai_resync_job',
            title: 'Full Civitai Metadata Resync',
            description: 'Deep background synchronization of metadata, tags, and images for all installed models.',
            category: 'Models',
            next_run: '2026-11-11T01:00:00Z',
            paused: false,
            trigger: 'interval[2 days, 0:00:00]',
            interval_seconds: 172800,
            last_run_at: '2026-11-09T01:00:00Z',
            last_status: 'success',
            last_duration_seconds: 14.5,
            last_error: null,
        },
    ],
    active_tasks: [
        { name: 'websocket_broadcast', done: false, cancelled: false },
    ],
    worker_pools: {
        image: { max_workers: 1, active_workers: 0, queued: 0 },
        llm: { max_workers: 1, active_workers: 0, queued: 0 },
        tts: { max_workers: 1, active_workers: 0, queued: 0 },
    },
    resync_status: {
        in_progress: false,
        mode: null,
        processed: 0,
        total: 0,
        current_model: null,
        started_at: null,
        last_completed_at: '2026-11-09T01:50:00Z',
        results: { success: 5, failed: 0, errors: [] },
    },
};

function renderWithClient(ui) {
    const queryClient = new QueryClient({
        defaultOptions: {
            queries: { retry: false },
        },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            {ui}
        </QueryClientProvider>
    );
}

describe('BackgroundTasks page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        settingsApi.getSchedulerStatus.mockResolvedValue(mockSchedulerData);
        settingsApi.runSchedulerJob.mockResolvedValue({ status: 'triggered', job_id: 'civitai_resync_random' });
        settingsApi.updateSchedulerJob.mockResolvedValue({ id: 'civitai_resync_random', paused: true });
        api.post.mockResolvedValue({ status: 'processing', count: 5, mode: 'random' });
    });

    it('renders scheduled recurring jobs and active tasks', async () => {
        renderWithClient(<BackgroundTasks />);

        expect(await screen.findByText('Random Batch Metadata Resync')).toBeInTheDocument();
        expect(await screen.findByText('Full Civitai Metadata Resync')).toBeInTheDocument();
        expect(screen.getByText('websocket_broadcast')).toBeInTheDocument();
        expect(screen.getByText('image')).toBeInTheDocument();
    });

    it('triggers immediate job run when clicking Run Now', async () => {
        renderWithClient(<BackgroundTasks />);

        const runButtons = await screen.findAllByText('Run Now');
        expect(runButtons.length).toBeGreaterThan(0);

        fireEvent.click(runButtons[0]);

        await waitFor(() => {
            expect(settingsApi.runSchedulerJob).toHaveBeenCalledWith('civitai_resync_random');
        });
    });

    it('toggles pause on a scheduled job', async () => {
        renderWithClient(<BackgroundTasks />);

        const pauseButtons = await screen.findAllByText('Pause');
        expect(pauseButtons.length).toBeGreaterThan(0);

        fireEvent.click(pauseButtons[0]);

        await waitFor(() => {
            expect(settingsApi.updateSchedulerJob).toHaveBeenCalledWith('civitai_resync_random', { paused: true });
        });
    });

    it('triggers random batch metadata resync', async () => {
        renderWithClient(<BackgroundTasks />);

        const randomBatchBtn = await screen.findByRole('button', { name: /run random batch metadata resync for 5 models/i });
        fireEvent.click(randomBatchBtn);

        await waitFor(() => {
            expect(api.post).toHaveBeenCalledWith('/api/v2/models/maintenance/resync-all', {
                mode: 'random',
                sample_size: 5,
            });
        });
    });

    it('triggers full deep metadata resync', async () => {
        renderWithClient(<BackgroundTasks />);

        const fullResyncBtn = await screen.findByRole('button', { name: /run full deep metadata resync for all models/i });
        fireEvent.click(fullResyncBtn);

        await waitFor(() => {
            expect(api.post).toHaveBeenCalledWith('/api/v2/models/maintenance/resync-all', {
                mode: 'full',
                sample_size: undefined,
            });
        });
    });

    it('renders query error state on fetch failure', async () => {
        settingsApi.getSchedulerStatus.mockRejectedValue(new Error('Network error'));

        renderWithClient(<BackgroundTasks />);

        expect(await screen.findByText(/Could not load your background tasks/i)).toBeInTheDocument();
    });
});
