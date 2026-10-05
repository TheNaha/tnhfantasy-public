import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * "Use Prompt" incremented the usage counter and then copied the text.
 *
 * The increment is `await`ed FIRST and succeeds, so on a non-secure origin
 * (`navigator.clipboard` undefined — measured: `http://100.150.0.4:5174` →
 * `{"secure":false,"clip":false}`) the usage count went up and then
 * `navigator.clipboard.writeText(...)` threw a SYNCHRONOUS TypeError before any
 * promise existed. Neither `.then` nor `.catch` could run: the user got no
 * feedback of any kind about a click that visibly did something server-side.
 *
 * Note the prior audit claimed this "reports success on a rejected copy". That
 * is refuted — there was a `.catch` at the old line 54. The defect is the
 * ABSENT-property case, where no promise is ever created and `.catch` is not a
 * guard.
 */

const prompts = [{
    id: 'p-1',
    name: 'Portrait',
    text: 'a weathered lighthouse keeper, dramatic rim light',
    category: 'Portrait',
    is_favorite: false,
    usage_count: 3,
}];

const mutateAsync = vi.hoisted(() => vi.fn());
const toastMock = vi.hoisted(() => {
    const fn = vi.fn();
    fn.success = vi.fn();
    fn.error = vi.fn();
    return fn;
});

vi.mock('../hooks/usePrompts', () => ({
    usePrompts: () => ({ data: prompts, isLoading: false }),
    usePromptCategories: () => ({ data: ['All', 'Portrait'] }),
    useDeletePrompt: () => ({ mutate: vi.fn() }),
    useUpdatePrompt: () => ({ mutate: vi.fn() }),
    useIncrementPromptUsage: () => ({ mutateAsync }),
    useImportPrompts: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock('../api/promptsApi', () => ({
    default: { exportAll: vi.fn() },
}));
vi.mock('react-hot-toast', () => ({ default: toastMock }));
vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}));

import Prompts from './Prompts';

function renderPage() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter><Prompts /></MemoryRouter>
        </QueryClientProvider>
    );
}

const clickUse = () => fireEvent.click(screen.getByRole('button', { name: /Use Prompt/i }));

describe('Prompts "Use Prompt" on an insecure origin', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mutateAsync.mockResolvedValue({});
    });
    afterEach(() => vi.unstubAllGlobals());

    it('increments the usage counter even though the copy cannot happen', async () => {
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });

        renderPage();
        clickUse();

        // The increment is a real server-side write. It happened first and it
        // still happened; the user should be told what actually occurred.
        await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith('p-1'), { timeout: 1000 });
        expect(toastMock.success).toHaveBeenCalled();
    });

    it('gives the user feedback, which the synchronous throw swallowed entirely', async () => {
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });

        renderPage();
        clickUse();

        // Before the fix this was silent: a visible action, a server-side
        // counter increment, and no message at all.
        await waitFor(
            () => expect(toastMock.success).toHaveBeenCalledWith(expect.stringContaining('selected'), expect.anything()),
            { timeout: 1000 }
        );
    });

    it('claims the copy only when the copy happened', async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });

        renderPage();
        clickUse();

        await waitFor(
            () => expect(toastMock.success).toHaveBeenCalledWith(expect.stringContaining('copied'), expect.anything()),
            { timeout: 1000 }
        );
        expect(writeText).toHaveBeenCalledWith(prompts[0].text);
    });

    it('does not throw out of the click handler', async () => {
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });

        renderPage();
        expect(clickUse).not.toThrow();

        await waitFor(() => expect(mutateAsync).toHaveBeenCalled(), { timeout: 1000 });
    });
});