import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ProviderCostDashboard from './ProviderCostDashboard';

const mockApi = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../api/client', () => ({ api: mockApi }));

describe('ProviderCostDashboard', () => {
    let queryClient;

    beforeEach(() => {
        vi.clearAllMocks();
        queryClient = new QueryClient({
            defaultOptions: {
                queries: { retry: false },
            },
        });
    });

    it('renders correctly when /api/jobs returns an object with a jobs array', async () => {
        mockApi.get.mockResolvedValueOnce({
            jobs: [
                {
                    id: 'job-1',
                    provider_id: 'fal-ai',
                    status: 'completed',
                    estimated_cost_cents: 150,
                    started_at: '2026-11-04T10:00:00Z',
                    completed_at: '2026-11-04T10:00:10Z',
                },
            ],
            total: 1,
        });

        render(
            <MemoryRouter>
                <QueryClientProvider client={queryClient}>
                    <ProviderCostDashboard />
                </QueryClientProvider>
            </MemoryRouter>
        );

        await waitFor(() => {
            expect(screen.getByText('Provider Cost Dashboard')).toBeInTheDocument();
        });

        expect(screen.getAllByText('fal-ai').length).toBeGreaterThan(0);
        expect(screen.getAllByText('$1.50').length).toBeGreaterThan(0);
    });

    it('renders correctly when /api/jobs returns a raw array', async () => {
        mockApi.get.mockResolvedValueOnce([
            {
                id: 'job-2',
                provider_id: 'runware',
                status: 'completed',
                estimated_cost_cents: 200,
                started_at: '2026-11-04T11:00:00Z',
                completed_at: '2026-11-04T11:00:05Z',
            },
        ]);

        render(
            <MemoryRouter>
                <QueryClientProvider client={queryClient}>
                    <ProviderCostDashboard />
                </QueryClientProvider>
            </MemoryRouter>
        );

        await waitFor(() => {
            expect(screen.getByText('Provider Cost Dashboard')).toBeInTheDocument();
        });

        expect(screen.getAllByText('runware').length).toBeGreaterThan(0);
        expect(screen.getAllByText('$2.00').length).toBeGreaterThan(0);
    });

    it('renders empty state when there are no jobs', async () => {
        mockApi.get.mockResolvedValueOnce({ jobs: [], total: 0 });

        render(
            <MemoryRouter>
                <QueryClientProvider client={queryClient}>
                    <ProviderCostDashboard />
                </QueryClientProvider>
            </MemoryRouter>
        );

        await waitFor(() => {
            expect(screen.getByText('No cost data yet')).toBeInTheDocument();
        });
    });
});
