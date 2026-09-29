/**
 * "Esc → Close modals", as `KeyboardShortcutsModal.jsx:16` advertises it.
 *
 * Sixteen overlays were hand-rolled with `fixed inset-0` and no Escape
 * handling, no portal and no `role="dialog"`, while `ModalOverlay` has all
 * three and 22 consumers. This file covers the subset converted to
 * `useEscapeKey`; converting the rest is a separate, larger diff and is
 * reported as not-done rather than half-applied.
 *
 * Every case renders the REAL component with the REAL `useEscapeKey` and fires
 * a real `keydown` on `window`, the event the hook listens for. Mocking the
 * hook would have made the suite pass whether or not the component called it —
 * which is the failure mode the 2026-09-29 and 2026-09-29b audits both found
 * elsewhere in this repo.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, api: apiMock };
});

const escape = () => fireEvent.keyDown(window, { key: 'Escape' });

function wrap(node) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
    return render(<QueryClientProvider client={queryClient}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockResolvedValue([]);
    localStorage.setItem('tnhcomfy_setup_complete', 'true');
});

describe('Escape closes the overlays that were converted', () => {
    it('CollectionsPanel', async () => {
        const CollectionsPanel = (await import('../components/collections/CollectionsPanel')).default;
        const onClose = vi.fn();
        wrap(<CollectionsPanel isOpen onClose={onClose} />);
        await waitFor(() => expect(screen.getByText('Collections')).toBeInTheDocument());
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('CollectionsPanel ignores Escape while it is closed', async () => {
        const CollectionsPanel = (await import('../components/collections/CollectionsPanel')).default;
        const onClose = vi.fn();
        wrap(<CollectionsPanel isOpen={false} onClose={onClose} />);
        escape();
        expect(onClose).not.toHaveBeenCalled();
    });

    it('ImageComparison', async () => {
        const { ImageComparison } = await import('../components/dashboard/ImageComparison');
        const onClose = vi.fn();
        wrap(<ImageComparison images={[]} onClose={onClose} />);
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('ProviderModal', async () => {
        const ProviderModal = (await import('../components/providers/ProviderModal')).default;
        const onClose = vi.fn();
        wrap(<ProviderModal provider={null} onClose={onClose} onSave={vi.fn()} saveProvider={vi.fn()} />);
        await waitFor(() => expect(document.body.textContent).toMatch(/provider/i));
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('AddModelToProviderModal', async () => {
        const AddModelToProviderModal = (await import('../components/providers/AddModelToProviderModal')).default;
        const onClose = vi.fn();
        wrap(<AddModelToProviderModal providers={[]} onClose={onClose} />);
        await waitFor(() => expect(document.body.textContent).toMatch(/model/i));
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('ModelImportCard', async () => {
        const ModelImportCard = (await import('../components/model-manager/ModelImportCard')).default;
        const onCancel = vi.fn();
        wrap(<ModelImportCard model={{ id: 1, name: 'x' }} onCancel={onCancel} />);
        escape();
        expect(onCancel).toHaveBeenCalled();
    });

    it('LorebookFormModal', async () => {
        const Lorebooks = (await import('./Lorebooks')).default;
        wrap(<Lorebooks />);
        await waitFor(() => expect(screen.getByText('Lorebooks')).toBeInTheDocument());
        // "New Lorebook" is both the toolbar button and the modal heading, so
        // the heading is scoped by the form's own placeholder instead.
        fireEvent.click(screen.getByRole('button', { name: /new lorebook/i }));
        await screen.findByPlaceholderText(/lorebook name/i);
        escape();
        await waitFor(() => expect(screen.queryByPlaceholderText(/lorebook name/i)).not.toBeInTheDocument());
    });

    it('Locations form', async () => {
        const Locations = (await import('./Locations')).default;
        wrap(<Locations />);
        await waitFor(() => expect(screen.getByText('Locations')).toBeInTheDocument());
        fireEvent.click(screen.getByRole('button', { name: /new location/i }));
        await waitFor(() => expect(screen.getByPlaceholderText(/location name/i)).toBeInTheDocument());
        escape();
        await waitFor(() => expect(screen.queryByPlaceholderText(/location name/i)).not.toBeInTheDocument());
    });
});
