import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import LogsTab from './LogsTab';
import { providersApi } from '../../../api';

function renderLogsTab(providerId = 'modal-test') {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <LogsTab providerId={providerId} />
        </QueryClientProvider>
    );
}

describe('LogsTab', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('renders deployment details and terminal output when deployment exists', async () => {
        vi.spyOn(providersApi, 'getLogs').mockResolvedValue({
            provider_id: 'modal-test',
            deploy: {
                target: 'image',
                artifact: 'comfy-modal-stack',
                transport: 'modal',
                elapsed_seconds: 18.5,
                ok: true,
                exit_code: 0,
                timestamp: '2026-10-15T10:00:00Z',
                output: 'Modal build completed successfully.\nReady for inference.',
            },
            recent_failures: [],
            diagnostics: { warnings: [], errors: [] },
        });

        renderLogsTab('modal-test');

        await waitFor(() => {
            expect(screen.getByText(/Latest Cloud Deployment/i)).toBeInTheDocument();
            expect(screen.getByText(/Succeeded/i)).toBeInTheDocument();
            expect(screen.getByText(/comfy-modal-stack/i)).toBeInTheDocument();
            expect(screen.getByText(/Modal build completed successfully/i)).toBeInTheDocument();
            expect(screen.getByText(/No recent job failures on record/i)).toBeInTheDocument();
        });
    });

    it('renders recent job failures with expandable traces', async () => {
        vi.spyOn(providersApi, 'getLogs').mockResolvedValue({
            provider_id: 'modal-test',
            deploy: null,
            recent_failures: [
                {
                    id: 'job-err-12345678',
                    task_type: 'image',
                    completed_at: '2026-10-15T10:15:00Z',
                    error: 'CUDA Out Of Memory: Allocated 24GB exceeds GPU limit',
                    message: 'Allocation failed on worker pod',
                },
            ],
            diagnostics: { warnings: [], errors: [] },
        });

        renderLogsTab('modal-test');

        await waitFor(() => {
            expect(screen.getByText(/Recent Job Execution Failures/i)).toBeInTheDocument();
            expect(screen.getByText(/Job job-err-/i)).toBeInTheDocument();
            expect(screen.getByText(/CUDA Out Of Memory/i)).toBeInTheDocument();
        });

        // Click to expand failure details
        const toggleBtn = screen.getByRole('button', { name: /Toggle failure details/i });
        fireEvent.click(toggleBtn);

        await waitFor(() => {
            expect(screen.getByText(/Full Error Trace:/i)).toBeInTheDocument();
        });
    });

    it('renders health warnings and errors if diagnostics has alerts', async () => {
        vi.spyOn(providersApi, 'getLogs').mockResolvedValue({
            provider_id: 'modal-test',
            deploy: null,
            recent_failures: [],
            diagnostics: {
                warnings: ['High latency observed on Modal endpoint'],
                errors: ['401 Unauthorized: Modal token invalid'],
            },
        });

        renderLogsTab('modal-test');

        await waitFor(() => {
            expect(screen.getByText(/Health Diagnostics & Warnings/i)).toBeInTheDocument();
            expect(screen.getByText(/High latency observed on Modal endpoint/i)).toBeInTheDocument();
            expect(screen.getByText(/401 Unauthorized: Modal token invalid/i)).toBeInTheDocument();
        });
    });
});
