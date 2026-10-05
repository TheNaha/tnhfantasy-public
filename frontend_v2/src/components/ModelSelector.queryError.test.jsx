import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

/**
 * `ModelSelector`'s own infinite query — a 503 must not read as an empty
 * library. Its own file because `InstalledTab` mocks the same module.
 */
const listState = vi.hoisted(() => ({
    isError: false,
    error: null,
    refetch: vi.fn(),
    pages: null,
}));

vi.mock('@tanstack/react-query', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useInfiniteQuery: () => ({
            data: listState.pages,
            hasNextPage: false,
            isFetching: false,
            isFetchingNextPage: false,
            isError: listState.isError,
            error: listState.error,
            refetch: listState.refetch,
        }),
    };
});

import ModelSelector from './ModelSelector';

const ONE_MODEL = {
    model_id: 'm1',
    name: 'alpha',
    display_name: 'Alpha',
    version_id: 'v1',
    description: '',
    base_model: 'SDXL',
    type: 'Checkpoint',
    nsfw: false,
    size: 1,
    downloadUrl: '',
    file_name: 'alpha.safetensors',
    preview: null,
};

function renderSelector() {
    return render(
        <MemoryRouter>
            <ModelSelector autoOpen value={null} onChange={() => {}} directory="loras" label="LoRAs" />
        </MemoryRouter>
    );
}

describe('ModelSelector — a failed model fetch is not an empty model library', () => {
    it('states the failure instead of "No models found"', () => {
        listState.isError = true;
        listState.error = new Error('503 from /api/files');
        listState.pages = null;

        renderSelector();

        expect(screen.getAllByRole('alert').length).toBeGreaterThan(0);
        expect(screen.queryByText('No models found')).toBeNull();
        expect(screen.queryByText('No models match your filters')).toBeNull();
    });

    it('offers a retry wired to the query refetch', () => {
        listState.isError = true;
        listState.refetch.mockClear();

        renderSelector();

        screen.getAllByRole('button', { name: /try again/i })[0].click();
        expect(listState.refetch).toHaveBeenCalled();
    });

    it('still shows the empty copy when the fetch succeeded and returned nothing', () => {
        listState.isError = false;
        listState.error = null;
        listState.pages = { pages: [] };

        renderSelector();

        expect(screen.getByText('No models found')).toBeTruthy();
    });

    it('renders the models when the fetch succeeded', () => {
        listState.isError = false;
        listState.pages = { pages: [{ files: [ONE_MODEL], directory: 'loras' }] };

        renderSelector();

        expect(screen.queryByText('No models found')).toBeNull();
        expect(screen.getAllByText('Alpha').length).toBeGreaterThan(0);
    });

    it('does not render an error branch when the query is disabled (no directory)', () => {
        // `initialModels` covers the no-`directory` path, where the query is
        // disabled. The error branch must be unreachable there, not merely
        // unlikely: a disabled query has no error to report.
        listState.isError = false;
        listState.pages = null;

        render(
            <MemoryRouter>
                <ModelSelector autoOpen value={null} onChange={() => {}} initialModels={[]} />
            </MemoryRouter>
        );

        expect(screen.queryByRole('alert')).toBeNull();
    });
});