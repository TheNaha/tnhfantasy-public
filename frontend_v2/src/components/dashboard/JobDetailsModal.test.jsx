import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import JobDetailsModal from './JobDetailsModal';

describe('JobDetailsModal', () => {
    it('renders basic job status without timings', () => {
        const job = {
            id: 'job-test-1234',
            status: 'completed',
            created_at: '2026-11-08T00:00:00Z',
            completed_at: '2026-11-08T00:00:05Z',
            metadata_: {
                prompt: 'a beautiful sunset over mountains',
            },
        };

        render(<JobDetailsModal job={job} onClose={vi.fn()} />);

        expect(screen.getByRole('dialog', { name: 'Job Details' })).toBeInTheDocument();
        expect(screen.getByText('job-test-1234')).toBeInTheDocument();
        expect(screen.getByText('completed')).toBeInTheDocument();
        expect(screen.getByText('a beautiful sunset over mountains')).toBeInTheDocument();
        expect(screen.queryByTestId('generation-telemetry')).not.toBeInTheDocument();
    });

    it('renders Generation Telemetry breakdown when timings are present', () => {
        const job = {
            id: 'job-test-5678',
            status: 'completed',
            created_at: '2026-11-08T00:00:00Z',
            completed_at: '2026-11-08T00:00:04Z',
            timings: {
                queue_seconds: 0.12,
                model_load_seconds: 1.25,
                sampling_seconds: 2.10,
                transfer_seconds: 0.35,
                processing_seconds: 0.15,
                total_backend_seconds: 3.97,
                total_e2e_seconds: 4.02,
            },
            metadata_: {
                prompt: 'a cybernetic wolf in neon city',
            },
        };

        render(<JobDetailsModal job={job} onClose={vi.fn()} />);

        const telemetry = screen.getByTestId('generation-telemetry');
        expect(telemetry).toBeInTheDocument();
        expect(screen.getByText('Generation Telemetry')).toBeInTheDocument();
        expect(screen.getByText('4.02s')).toBeInTheDocument();
        expect(screen.getByText('1.25s')).toBeInTheDocument();
        expect(screen.getByText('2.10s')).toBeInTheDocument();
    });
});
