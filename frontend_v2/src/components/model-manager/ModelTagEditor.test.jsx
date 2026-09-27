import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

/**
 * The write side of model tags.
 *
 * Until this existed, `ModelTag` was populate-only from a CivitAI resync and
 * the resync deleted its own rows — so every tag in the app was scraped and
 * there was nowhere to record one the user cared about. These tests pin the
 * three things that make the feature honest rather than merely present:
 *
 *  - the request shape (right endpoint, right body),
 *  - that a delete control appears only for a tag proven to be the user's,
 *  - and that the backend's refusal — a 404 for a CivitAI tag — is reported,
 *    not leaked as an unhandled rejection.
 */

const mockModelsApi = vi.hoisted(() => ({
    listTags: vi.fn(),
    addTag: vi.fn(),
    removeTag: vi.fn(),
}));

vi.mock('../../api', async (importOriginal) => ({
    ...(await importOriginal()),
    modelsApi: mockModelsApi,
}));

vi.mock('react-hot-toast', () => {
    const toast = { success: vi.fn(), error: vi.fn(), promise: vi.fn() };
    return { default: toast, toast, Toaster: () => null };
});

import toast from 'react-hot-toast';
import { ModelTagEditor } from './ModelDetailsModal';

const MODEL_ID = 'model-abc';

let queryClient;

/** Unhandled rejections seen while a test runs, so a test can assert on zero. */
let unhandled;
const recordUnhandled = (reason) => unhandled.push(reason);

function renderEditor(props = {}) {
    render(
        <QueryClientProvider client={queryClient}>
            <ModelTagEditor modelId={MODEL_ID} {...props} />
        </QueryClientProvider>
    );
}

const addInput = () => screen.getByLabelText('Add a tag');
const addButton = () => screen.getByRole('button', { name: 'Add' });

describe('ModelTagEditor', () => {
    beforeEach(() => {
        unhandled = [];
        process.on('unhandledRejection', recordUnhandled);
        queryClient = new QueryClient({
            defaultOptions: { queries: { retry: false } },
        });
        mockModelsApi.listTags.mockReset();
        mockModelsApi.addTag.mockReset();
        mockModelsApi.removeTag.mockReset();
        toast.success.mockClear();
        toast.error.mockClear();
    });

    afterEach(() => {
        process.off('unhandledRejection', recordUnhandled);
    });

    describe('provenance decides who may delete', () => {
        it('offers a delete control only for a tag the backend reports as user', async () => {
            mockModelsApi.listTags.mockResolvedValue({
                tags: [
                    { tag: 'anime', source: 'civitai' },
                    { tag: 'character-x', source: 'user' },
                ],
            });
            renderEditor({ tags: ['anime', 'character-x'] });

            await waitFor(() =>
                expect(screen.getByLabelText('Remove tag character-x')).toBeInTheDocument()
            );
            expect(screen.getByText('anime')).toBeInTheDocument();
            expect(screen.queryByLabelText('Remove tag anime')).toBeNull();
            expect(screen.getByRole('heading', { name: /your tags/i })).toBeInTheDocument();
        });

        it('offers no delete control at all while provenance is still loading', async () => {
            // A tag with no provenance is an unknown tag, not a user tag. The
            // backend 404s a delete it will not honour, so the control must not
            // be on screen yet.
            mockModelsApi.listTags.mockReturnValue(new Promise(() => {}));
            renderEditor({ tags: ['anime', 'character-x'] });

            await waitFor(() => expect(screen.getByText('anime')).toBeInTheDocument());
            expect(screen.queryByRole('button', { name: /^Remove tag/ })).toBeNull();
        });

        it('offers no delete control when provenance could not be loaded', async () => {
            mockModelsApi.listTags.mockRejectedValue(new Error('boom'));
            renderEditor({ tags: ['anime'] });

            await waitFor(() => expect(mockModelsApi.listTags).toHaveBeenCalled());
            await waitFor(() => expect(screen.getByText('anime')).toBeInTheDocument());
            expect(screen.queryByRole('button', { name: /^Remove tag/ })).toBeNull();
        });

        it('treats a tag absent from the provenance response as undeletable', async () => {
            // The list payload can carry a tag the provenance response has not
            // caught up with. Absence is not permission.
            mockModelsApi.listTags.mockResolvedValue({
                tags: [{ tag: 'anime', source: 'civitai' }],
            });
            renderEditor({ tags: ['anime', 'just-added'] });

            await waitFor(() => expect(screen.getByText('just-added')).toBeInTheDocument());
            expect(screen.queryByLabelText('Remove tag just-added')).toBeNull();
        });
    });

    describe('adding a tag', () => {
        it('posts the trimmed tag to the model it was typed against', async () => {
            mockModelsApi.listTags.mockResolvedValue({ tags: [] });
            mockModelsApi.addTag.mockResolvedValue({ tag: 'kneeling hands up', source: 'user', created: true });
            renderEditor({ tags: [] });

            await waitFor(() => expect(mockModelsApi.listTags).toHaveBeenCalledWith(MODEL_ID));
            fireEvent.change(addInput(), { target: { value: '  kneeling hands up  ' } });
            fireEvent.click(addButton());

            await waitFor(() =>
                expect(mockModelsApi.addTag).toHaveBeenCalledWith(MODEL_ID, 'kneeling hands up')
            );
            expect(mockModelsApi.addTag).toHaveBeenCalledTimes(1);
        });

        it('submits from the form, so Enter needs no bespoke key handler', async () => {
            // jsdom does not implement implicit form submission, and it should
            // not have to: a single-input form submits on Enter in every real
            // browser, and a hand-rolled onKeyDown would then double-submit.
            mockModelsApi.listTags.mockResolvedValue({ tags: [] });
            mockModelsApi.addTag.mockResolvedValue({ tag: 'anime', source: 'user', created: true });
            renderEditor({ tags: [] });

            await waitFor(() => expect(mockModelsApi.listTags).toHaveBeenCalled());
            fireEvent.change(addInput(), { target: { value: 'anime' } });
            fireEvent.submit(addInput().closest('form'));

            await waitFor(() => expect(mockModelsApi.addTag).toHaveBeenCalledWith(MODEL_ID, 'anime'));
        });

        it('does not submit a blank or whitespace-only tag', async () => {
            mockModelsApi.listTags.mockResolvedValue({ tags: [] });
            renderEditor({ tags: [] });

            await waitFor(() => expect(mockModelsApi.listTags).toHaveBeenCalled());
            for (const value of ['', '   ']) {
                fireEvent.change(addInput(), { target: { value } });
                fireEvent.submit(addInput().closest('form'));
            }

            expect(mockModelsApi.addTag).not.toHaveBeenCalled();
        });

        it('makes the new tag immediately deletable and invalidates both model lists', async () => {
            // "Immediately usable as a filter" needs a round trip (the list has
            // to refetch) but the provenance cache does not: patching it is what
            // makes the tag appear, and be removable, without a second request.
            const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
            mockModelsApi.listTags.mockResolvedValue({ tags: [] });
            mockModelsApi.addTag.mockResolvedValue({ tag: 'anime', source: 'user', created: true });
            renderEditor({ tags: [] });

            await waitFor(() => expect(mockModelsApi.listTags).toHaveBeenCalled());
            fireEvent.change(addInput(), { target: { value: 'anime' } });
            fireEvent.click(addButton());

            await waitFor(() => expect(screen.getByLabelText('Remove tag anime')).toBeInTheDocument());
            expect(queryClient.getQueryData(['model-tags', MODEL_ID])).toEqual({
                tags: [{ tag: 'anime', source: 'user' }],
            });
            // Both lists, not just one: the generator's ModelSelector and the
            // model manager's Installed tab do not share a key prefix, and the
            // picker is the surface someone hunting for a LoRA actually uses.
            expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['models'] });
            expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['installed-models'] });
        });

        it('says the tag was already there when the backend reports created:false', async () => {
            mockModelsApi.listTags.mockResolvedValue({
                tags: [{ tag: 'anime', source: 'civitai' }],
            });
            mockModelsApi.addTag.mockResolvedValue({ tag: 'anime', source: 'civitai', created: false });
            renderEditor({ tags: ['anime'] });

            await waitFor(() => expect(mockModelsApi.listTags).toHaveBeenCalled());
            fireEvent.change(addInput(), { target: { value: 'anime' } });
            fireEvent.click(addButton());

            await waitFor(() => expect(toast.success).toHaveBeenCalledWith(
                expect.stringMatching(/already on this model/i)
            ));
            // Still not deletable: the backend keeps a CivitAI row as the one
            // row for (model_id, tag), so a user "adding" it does not take
            // ownership of it.
            expect(screen.queryByLabelText('Remove tag anime')).toBeNull();
        });

        it('reports a rejected add instead of throwing', async () => {
            mockModelsApi.listTags.mockResolvedValue({ tags: [] });
            mockModelsApi.addTag.mockRejectedValue(
                Object.assign(new Error('Tag must be 64 characters or fewer'), { status: 422 })
            );
            renderEditor({ tags: [] });

            await waitFor(() => expect(mockModelsApi.listTags).toHaveBeenCalled());
            fireEvent.change(addInput(), { target: { value: 'x'.repeat(80) } });
            fireEvent.click(addButton());

            await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
                expect.stringContaining('Tag must be 64 characters or fewer')
            ));
            expect(unhandled).toEqual([]);
        });
    });

    describe('removing a tag', () => {
        it('deletes the tag and drops it from the provenance cache', async () => {
            const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
            mockModelsApi.listTags.mockResolvedValue({
                tags: [{ tag: 'anime', source: 'user' }],
            });
            mockModelsApi.removeTag.mockResolvedValue({ status: 'success' });
            renderEditor({ tags: ['anime'] });

            await waitFor(() => expect(screen.getByLabelText('Remove tag anime')).toBeInTheDocument());
            fireEvent.click(screen.getByLabelText('Remove tag anime'));

            await waitFor(() =>
                expect(mockModelsApi.removeTag).toHaveBeenCalledWith(MODEL_ID, 'anime')
            );
            await waitFor(() => expect(screen.queryByLabelText('Remove tag anime')).toBeNull());
            expect(queryClient.getQueryData(['model-tags', MODEL_ID])).toEqual({ tags: [] });
            expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['installed-models'] });
        });

        it('surfaces a 404 refusal as a message about CivitAI, not an unhandled rejection', async () => {
            // A delete control only exists for a tag proven to be the user's, so
            // the 404 path is the race: a resync landed between the read and the
            // delete and the row is no longer ours. React Query routes the
            // rejection to the error handler, and the only acceptable outcomes
            // are "explained" or "crashed" — never a rejection nobody caught.
            mockModelsApi.listTags
                .mockResolvedValueOnce({ tags: [{ tag: 'anime', source: 'user' }] })
                .mockResolvedValue({ tags: [{ tag: 'anime', source: 'civitai' }] });
            mockModelsApi.removeTag.mockRejectedValue(
                Object.assign(new Error('No user tag'), { status: 404 })
            );
            renderEditor({ tags: ['anime'] });

            await waitFor(() => expect(screen.getByLabelText('Remove tag anime')).toBeInTheDocument());
            fireEvent.click(screen.getByLabelText('Remove tag anime'));

            await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
                expect.stringMatching(/CivitAI tag/i)
            ));
            expect(toast.error.mock.calls[0][0]).not.toMatch(/Could not remove tag/);
            expect(unhandled).toEqual([]);
            // The tag stays: the server refused, so claiming otherwise would lie.
            await waitFor(() => expect(screen.getByText('anime')).toBeInTheDocument());
            // The handler also re-reads provenance, so the delete control retires
            // instead of offering the same doomed click again.
            await waitFor(() => expect(screen.queryByLabelText('Remove tag anime')).toBeNull());
        });

        it('re-reads provenance after a 404, since our view of it was wrong', async () => {
            const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
            mockModelsApi.listTags.mockResolvedValue({
                tags: [{ tag: 'anime', source: 'user' }],
            });
            mockModelsApi.removeTag.mockRejectedValue(
                Object.assign(new Error('No user tag'), { status: 404 })
            );
            renderEditor({ tags: ['anime'] });

            await waitFor(() => expect(screen.getByLabelText('Remove tag anime')).toBeInTheDocument());
            fireEvent.click(screen.getByLabelText('Remove tag anime'));

            await waitFor(() =>
                expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['model-tags', MODEL_ID] })
            );
        });

        it('reports a non-404 failure as a plain failure', async () => {
            mockModelsApi.listTags.mockResolvedValue({
                tags: [{ tag: 'anime', source: 'user' }],
            });
            mockModelsApi.removeTag.mockRejectedValue(
                Object.assign(new Error('Internal Server Error'), { status: 500 })
            );
            renderEditor({ tags: ['anime'] });

            await waitFor(() => expect(screen.getByLabelText('Remove tag anime')).toBeInTheDocument());
            fireEvent.click(screen.getByLabelText('Remove tag anime'));

            await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
                'Could not remove tag: Internal Server Error'
            ));
            expect(toast.error.mock.calls[0][0]).not.toMatch(/CivitAI/);
            expect(unhandled).toEqual([]);
        });
    });
});
