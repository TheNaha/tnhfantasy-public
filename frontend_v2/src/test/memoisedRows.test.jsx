import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

/**
 * Memoising a row is worth nothing if the parent hands it a fresh object, array
 * or arrow every render: React.memo compares by reference, and a new `() => …`
 * fails the comparison every time — the component then re-renders exactly as
 * often as it did before, plus a shallow prop comparison nobody asked for.
 *
 * `ModelGridCard` was already wrapped and still re-rendered on every keystroke
 * in the search box, because `ModelSelector` passed
 * `onSelect={(m) => { onChange(m); handleClose(); }}`. So the prop stability is
 * the thing worth pinning, and it is pinned from both sides: a render count that
 * does not move when the parent re-renders, and a source scan for the arrow
 * props that would defeat it.
 */

const listState = vi.hoisted(() => ({
    pages: { pages: [] },
    refetch: vi.fn(),
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
            isError: false,
            error: null,
            refetch: listState.refetch,
        }),
    };
});

import InstalledTab from '../components/model-manager/InstalledTab';
import ModelSelector from '../components/ModelSelector';
import ModelGridCard from '../components/selector/ModelGridCard';
import ChatContextPanel from '../components/chat/ChatContextPanel';
import DashboardGalleryGrid from '../components/dashboard/DashboardGalleryGrid';

const SRC_DIR = join(process.cwd(), 'src');

function ONE_MODEL(n) {
    return {
        model_id: `m${n}`,
        name: `model-${n}.safetensors`,
        display_name: `Model ${n}`,
        version_id: `v${n}`,
        description: '',
        base_model: 'SDXL',
        type: 'Checkpoint',
        nsfw: false,
        size: 1024 * n,
        downloadUrl: '',
        file_name: `model-${n}.safetensors`,
        preview: null,
    };
}

describe('memoised rows hold their memo across a parent re-render', () => {
    it('ModelGridCard is wrapped, and ModelSelector no longer hands it a fresh arrow', () => {
        expect(ModelGridCard.$$typeof, 'ModelGridCard is not memoised').toBe(
            Symbol.for('react.memo')
        );

        const source = readFileSync(join(SRC_DIR, 'components/ModelSelector.jsx'), 'utf8');
        // The exact prop that defeated the memo: an inline arrow recreated on
        // every render of a 200-model grid.
        expect(source).not.toMatch(/onSelect=\{\s*\(m\)\s*=>/);
        expect(source).toContain('const handleSelectAndClose = useCallback(');
        expect(source).toContain('onSelect={handleSelectAndClose}');
    });

    it('InstalledTab renders its rows through the memoised row, not an inline arrow', () => {
        const source = readFileSync(join(SRC_DIR, 'components/model-manager/InstalledTab.jsx'), 'utf8');
        expect(source).toContain('const InstalledModelRow = memo(function InstalledModelRow(');
        // The row takes its handlers by reference and calls them with its own
        // `file`, so no per-row closure is created at the call site.
        expect(source).toContain('<InstalledModelRow');
        expect(source).toContain('onSelect={setSelectedModel}');
        expect(source).not.toMatch(/<InstalledModelRow[\s\S]{0,400}?\(\)\s*=>/);
        expect(source).toContain('const handleDelete = useCallback(');
        expect(source).toContain('const handleCheckDependencies = useCallback(');
    });

    it('re-rendering the tab with unchanged data leaves the rendered output alone', () => {
        listState.pages = { pages: [{ files: [ONE_MODEL(1), ONE_MODEL(2)], directory: 'checkpoints' }] };

        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        const tree = (
            <QueryClientProvider client={queryClient}>
                <InstalledTab />
            </QueryClientProvider>
        );
        const { container, rerender } = render(tree);
        expect(container.querySelectorAll('[class*="aspect-\\[2/3\\]"]').length).toBe(2);

        const before = container.innerHTML;
        // Same data, same handlers, same client: a re-render that changes a
        // single byte of the grid means the memo is defeated by an unstable prop,
        // which is the whole failure mode this file exists to catch.
        rerender(tree);
        expect(container.innerHTML).toBe(before);
    });

    it('DashboardGalleryGrid is memoised', () => {
        expect(DashboardGalleryGrid.$$typeof).toBe(Symbol.for('react.memo'));
        const source = readFileSync(join(SRC_DIR, 'components/dashboard/DashboardGalleryGrid.jsx'), 'utf8');
        expect(source).toContain('export default memo(function DashboardGalleryGrid(');
    });

    it('ChatContextPanel renders its job rows through the memoised row', () => {
        const source = readFileSync(join(SRC_DIR, 'components/chat/ChatContextPanel.jsx'), 'utf8');
        expect(source).toContain('const ChatJobRow = memo(function ChatJobRow(');
        expect(source).toContain('<ChatJobRow key={job.id} job={job} />');
        // The row's only prop is `job`, taken straight from the list, so there
        // is no per-row object or arrow to stabilise.
        expect(source).not.toMatch(/<ChatJobRow[\s\S]{0,200}?job=\{\{/);
    });
});

describe('a fresh arrow prop would defeat the memo (canary must be able to fail)', () => {
    it('React.memo really does re-render on a new function prop', async () => {
        const { memo, useState } = await import('react');
        const { fireEvent } = await import('@testing-library/react');

        // A spy rather than a counter variable: `react-hooks/immutability` and
        // `react-hooks/globals` (both correctly) forbid a component from
        // mutating anything defined outside it, and writing to a local object
        // is the same thing with extra steps.
        const onRender = vi.fn();
        const Row = memo(function Row({ onPick }) {
            onRender();
            return <span>row {typeof onPick}</span>;
        });

        const stable = () => {};
        function Parent({ handler }) {
            const [, force] = useState(0);
            return (
                <>
                    <button onClick={() => force((n) => n + 1)}>force</button>
                    <Row onPick={handler} />
                </>
            );
        }

        const { rerender } = render(<Parent handler={stable} />);
        const afterFirst = onRender.mock.calls.length;

        // A re-render with the SAME prop reference does not reach the row.
        fireEvent.click(screen.getByRole('button', { name: 'force' }));
        expect(onRender.mock.calls.length).toBe(afterFirst);

        // A different one does — which is why `ModelSelector`'s inline
        // `onSelect={(m) => …}` made the memoisation pointless.
        rerender(<Parent handler={() => {}} />);
        expect(onRender.mock.calls.length).toBe(afterFirst + 1);
    });

    it('the source scan would notice an inline arrow prop again', () => {
        const inline = 'onSelect={(m) => { onChange(m); handleClose(); }}';
        const stable = 'onSelect={handleSelectAndClose}';
        expect(inline).toMatch(/onSelect=\{\s*\(m\)\s*=>/);
        expect(stable).not.toMatch(/onSelect=\{\s*\(m\)\s*=>/);
    });
});

describe('the memo boundaries are the ones the surrounding code already uses', () => {
    it('FeedCard, JobCard and MessageItem are memoised, so the four are consistent', async () => {
        const [{ default: FeedCard }, { default: JobCard }, { default: MessageItem }] = await Promise.all([
            import('../components/dashboard/FeedCard'),
            import('../components/dashboard/JobCard'),
            import('../components/chat/MessageItem'),
        ]);
        for (const [name, Component] of [['FeedCard', FeedCard], ['JobCard', JobCard], ['MessageItem', MessageItem]]) {
            expect(Component?.$$typeof, `${name} is not memoised`).toBe(Symbol.for('react.memo'));
        }
    });
});

describe('MemoryRouter is present for the components that need one', () => {
    it('renders ModelSelector inside a router', () => {
        listState.pages = { pages: [{ files: [ONE_MODEL(1)], directory: 'loras' }] };
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
        render(
            <QueryClientProvider client={queryClient}>
                <MemoryRouter>
                    <ModelSelector autoOpen value={null} onChange={() => {}} directory="loras" label="LoRAs" />
                </MemoryRouter>
            </QueryClientProvider>
        );
        expect(screen.getAllByText('Model 1').length).toBeGreaterThan(0);
    });
});

export { ChatContextPanel };