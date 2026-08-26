import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import BatchGenerate from './BatchGenerate';

const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const fetchMock = vi.hoisted(() => vi.fn());

vi.mock('react-hot-toast', () => ({ default: mockToast }));

const createdJobs = [
    { id: 'j1', status: 'queued', metadata: { prompt: 'prompt-1', batch_index: 0, batch_total: 4, batch_preset: 'character_sheet' } },
    { id: 'j2', status: 'queued', metadata: { prompt: 'prompt-2', batch_index: 1, batch_total: 4, batch_preset: 'character_sheet' } },
    { id: 'j3', status: 'queued', metadata: { prompt: 'prompt-3', batch_index: 2, batch_total: 4, batch_preset: 'character_sheet' } },
    { id: 'j4', status: 'queued', metadata: { prompt: 'prompt-4', batch_index: 3, batch_total: 4, batch_preset: 'character_sheet' } },
];

function renderPage() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    render(
        <QueryClientProvider client={queryClient}>
            <BatchGenerate />
        </QueryClientProvider>
    );
    return { queryClient };
}

describe('BatchGenerate page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        globalThis.fetch = fetchMock;
        const jsonHeaders = new Headers({ 'content-type': 'application/json' });
        fetchMock.mockImplementation((url, init = {}) => {
            if ((init.method || 'GET') !== 'POST') {
                return Promise.resolve({ ok: true, status: 200, headers: jsonHeaders, json: async () => ({ files: [], total: 0 }) });
            }
            return Promise.resolve({
                ok: true,
                status: 200,
                headers: jsonHeaders,
                json: async () => ({ count: 4, jobs: createdJobs }),
            });
        });
    });

    function postCalls() {
        return fetchMock.mock.calls.filter(c => c[1]?.method === 'POST');
    }

    it('renders the main heading and subtitle', () => {
        renderPage();
        expect(screen.getByRole('heading', { name: 'Batch Generation Studio' })).toBeInTheDocument();
        expect(screen.getByText('Generate character sheets, scene variations, and concept grids')).toBeInTheDocument();
    });

    it('renders all presets with descriptions', () => {
        renderPage();
        expect(screen.getByText('Character Sheet')).toBeInTheDocument();
        expect(screen.getByText('Generate multiple angles/expressions of a character')).toBeInTheDocument();
        expect(screen.getByText('Scene Variations')).toBeInTheDocument();
        expect(screen.getByText('Concept Grid')).toBeInTheDocument();
    });

    it('shows unresolved character-sheet prompts by default', () => {
        renderPage();
        expect(screen.getByText('portrait of {char}, front view, neutral expression')).toBeInTheDocument();
        expect(screen.getByText('portrait of {char}, close-up, detailed face')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Generate 4 Images/ })).toBeInTheDocument();
    });

    it('resolves character name into generated prompts', () => {
        renderPage();
        fireEvent.change(screen.getByPlaceholderText('e.g. Elara Moonwhisper'), {
            target: { value: 'Elara Moonwhisper' },
        });
        expect(screen.getByText('portrait of Elara Moonwhisper, front view, neutral expression')).toBeInTheDocument();
        expect(screen.getByText('portrait of Elara Moonwhisper, three-quarter view, smiling')).toBeInTheDocument();
    });

    it('switches to the scene variations preset', () => {
        renderPage();
        fireEvent.click(screen.getByText('Scene Variations'));
        expect(screen.getByPlaceholderText('e.g. Enchanted Forest')).toBeInTheDocument();
        expect(screen.getByText('wide shot of {scene}, cinematic')).toBeInTheDocument();
        expect(screen.queryByText('portrait of {char}, front view, neutral expression')).not.toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('e.g. Enchanted Forest'), { target: { value: 'Old Forest' } });
        expect(screen.getByText('close-up of Old Forest, intimate')).toBeInTheDocument();
    });

    it('switches to the concept grid preset and resolves the base prompt', () => {
        renderPage();
        fireEvent.click(screen.getByText('Concept Grid'));
        expect(screen.getByPlaceholderText('e.g. a futuristic cityscape at sunset')).toBeInTheDocument();
        expect(screen.getByText('untitled concept, style A')).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('e.g. a futuristic cityscape at sunset'), {
            target: { value: 'a futuristic cityscape at sunset' },
        });
        expect(screen.getByText('a futuristic cityscape at sunset, style D')).toBeInTheDocument();
    });

    it('shows the base seed input only for non-random seed modes', () => {
        renderPage();
        expect(screen.queryByPlaceholderText('Base seed')).not.toBeInTheDocument();
        fireEvent.click(screen.getByText('fixed'));
        expect(screen.getByPlaceholderText('Base seed')).toBeInTheDocument();
    });

    it('generates jobs via POST /api/generate/batch with resolved prompts and toasts success', async () => {
        renderPage();
        fireEvent.change(screen.getByPlaceholderText('e.g. Elara Moonwhisper'), {
            target: { value: 'Elara Moonwhisper' },
        });
        fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));

        await waitFor(() => expect(postCalls()).toHaveLength(1));

        const [url, init] = postCalls()[0];
        expect(url).toBe('/api/generate/batch');
        const body = JSON.parse(init.body);
        expect(body.workflows).toHaveLength(4);
        expect(body.workflows[0].options.prompt).toBe('portrait of Elara Moonwhisper, front view, neutral expression');
        expect(body.workflows[0].options.width).toBe(512);
        expect(body.workflows[0].metadata.batch_total).toBe(4);
        expect(body.workflows[0].metadata.batch_preset).toBe('character_sheet');
        expect(typeof body.workflows[0].options.seed).toBe('number');

        await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Created 4 generation jobs'));
        expect(screen.getByText('Batch Jobs')).toBeInTheDocument();
        expect(screen.getAllByText('queued')).toHaveLength(4);
    });

    it('uses increment seed mode to derive sequential seeds from the base seed', async () => {
        renderPage();
        fireEvent.click(screen.getByText('increment'));
        fireEvent.change(screen.getByPlaceholderText('Base seed'), { target: { value: '42' } });
        fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));

        await waitFor(() => expect(postCalls()).toHaveLength(1));
        const body = JSON.parse(postCalls()[0][1].body);
        expect(body.workflows.map((w) => w.options.seed)).toEqual([42, 43, 44, 45]);
    });

    it('uses a fixed seed for all jobs in fixed seed mode', async () => {
        renderPage();
        fireEvent.click(screen.getByText('fixed'));
        fireEvent.change(screen.getByPlaceholderText('Base seed'), { target: { value: '777' } });
        fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));

        await waitFor(() => expect(postCalls()).toHaveLength(1));
        const body = JSON.parse(postCalls()[0][1].body);
        expect(body.workflows.map((w) => w.options.seed)).toEqual([777, 777, 777, 777]);
    });

    it('shows an error toast when batch generation fails', async () => {
        fetchMock.mockResolvedValue({
            ok: false,
            status: 500,
            headers: new Headers({ 'content-type': 'application/json' }),
            json: async () => ({ detail: 'Batch generation failed' }),
        });
        renderPage();
        fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));
        await waitFor(() => expect(mockToast.error).toHaveBeenCalledWith('Batch generation failed'));
    });

    it('reflects websocket-driven status changes without REST polling', async () => {
        const { queryClient } = renderPage();
        fireEvent.click(screen.getByRole('button', { name: /Generate 4 Images/ }));

        await waitFor(() => expect(screen.getAllByText('queued')).toHaveLength(4));
        const jobGets = fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/jobs/j'));
        expect(jobGets).toHaveLength(0);

        // Simulate the realtime bridge applying a JOB_COMPLETED payload.
        act(() => {
            queryClient.setQueryData(['jobs', 'j1'], {
                ...createdJobs[0],
                status: 'completed',
                outputs: [{ content: 'done_1.png' }],
            });
        });

        await waitFor(() => expect(screen.getByText('completed')).toBeInTheDocument());
        expect(screen.getByAltText('prompt-1')).toHaveAttribute('src', '/api/view/output/done_1.png');
    });
});