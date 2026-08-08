import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import QueueVisualization from './QueueVisualization';

// Mock react-query useQuery to feed the backend-shaped queue payload
vi.mock('@tanstack/react-query', () => ({
    useQuery: vi.fn(),
}));

import { useQuery } from '@tanstack/react-query';

// Mock framer-motion
vi.mock('framer-motion', () => ({
    motion: {
        div: ({ children, className, onClick, ...props }) => (
            <div className={className} onClick={onClick} {...props}>{children}</div>
        ),
    },
    AnimatePresence: ({ children }) => <>{children}</>,
}));

describe('QueueVisualization', () => {
    const mockOnJobClick = vi.fn();

    beforeEach(() => {
        vi.clearAllMocks();
        // Setup default mock return value (backend /api/jobs/queue shape)
        useQuery.mockReturnValue({
            data: {
                queue: [
                    {
                        id: '1',
                        task_type: 'image',
                        status: 'generating',
                        position: 0,
                        progress: 50,
                        eta_seconds: 15,
                        prompt: 'Running Job',
                    },
                    {
                        id: '2',
                        task_type: 'image',
                        status: 'pending',
                        position: 1,
                        progress: 0,
                        eta_seconds: 45,
                        prompt: 'Pending Job',
                    },
                ],
                avg_duration_seconds: { image: 30 },
                has_history: true,
                total_pending: 1,
                total_running: 1,
            },
            isLoading: false,
        });
    });

    it('renders the queue summary header', () => {
        render(<QueueVisualization onJobClick={mockOnJobClick} />);
        expect(screen.getByText(/1\s*running,\s*1\s*pending/i)).toBeInTheDocument();
    });

    it('toggle button has accessibility attributes', () => {
        render(<QueueVisualization onJobClick={mockOnJobClick} />);

        // Find the toggle button (it's the first button)
        const buttons = screen.getAllByRole('button');
        const toggleButton = buttons[0];

        expect(toggleButton).toHaveAttribute('aria-expanded');
        expect(toggleButton).toHaveAttribute('aria-controls');
    });

    it('renders job list items as accessible buttons', () => {
        render(<QueueVisualization onJobClick={mockOnJobClick} />);

        // We expect job items to be accessible via button role
        const jobButtons = screen.getAllByRole('button');

        // We have 1 toggle button + 2 job items = 3 buttons expected
        expect(jobButtons.length).toBeGreaterThanOrEqual(3);
    });

    it('job items have descriptive aria labels', () => {
        render(<QueueVisualization onJobClick={mockOnJobClick} />);

        const runningJobText = screen.getByText('Running Job');
        const jobButton = runningJobText.closest('button');

        expect(jobButton).toBeInTheDocument();
        expect(jobButton).toHaveAttribute('aria-label');
        expect(jobButton.getAttribute('aria-label')).toContain('Running Job');
        expect(jobButton.getAttribute('aria-label')).toContain('generating');
    });
});
