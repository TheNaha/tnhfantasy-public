import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import QueueVisualization from './QueueVisualization';
import { useJobStore } from '../store/jobStore';

// Mock dependencies
vi.mock('../store/jobStore', () => ({
    useJobStore: vi.fn(),
}));

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
        // Setup default mock return value
        useJobStore.mockImplementation((selector) => {
            if (selector) {
                return [
                    {
                        id: '1',
                        status: 'running',
                        prompt: 'Running Job',
                        progress: 50,
                        started_at: new Date().toISOString()
                    },
                    {
                        id: '2',
                        status: 'pending',
                        prompt: 'Pending Job',
                        queue_position: 1
                    },
                ];
            }
            return {
                jobs: [],
                jobs: []
            };
        });
    });

    it('renders the queue summary header', () => {
        render(<QueueVisualization onJobClick={mockOnJobClick} />);
        expect(screen.getByText(/Queue \(1 running, 1 pending\)/)).toBeInTheDocument();
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
        expect(jobButton.getAttribute('aria-label')).toContain('running');
    });
});
