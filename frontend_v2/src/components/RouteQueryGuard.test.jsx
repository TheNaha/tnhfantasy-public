import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ChatRouteGuard, StoryRouteGuard } from './RouteQueryGuard';
import NotFound from '../pages/NotFound';

const mockNavigate = vi.hoisted(() => vi.fn());
const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const mockChatQuery = vi.hoisted(() => ({ isError: false }));
const mockStoryQuery = vi.hoisted(() => ({ isError: false }));

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('react-hot-toast', () => ({ default: mockToast }));

vi.mock('../hooks/useChats', () => ({
    useChat: () => mockChatQuery,
}));

vi.mock('../hooks/useStories', () => ({
    useStory: () => mockStoryQuery,
}));

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

function renderGuard(guard) {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={['/chat/abc']}>
                <Routes>
                    <Route path="/chat/:chatId" element={guard} />
                    <Route path="/chat" element={<div>chat list</div>} />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('RouteQueryGuard', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockChatQuery.isError = false;
        mockStoryQuery.isError = false;
    });

    it('renders children while the query is healthy', () => {
        renderGuard(
            <ChatRouteGuard chatId="abc">
                <div>protected content</div>
            </ChatRouteGuard>
        );
        expect(screen.getByText('protected content')).toBeInTheDocument();
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('toasts and redirects to the fallback when the chat is missing', async () => {
        mockChatQuery.isError = true;
        renderGuard(
            <ChatRouteGuard chatId="abc">
                <div>protected content</div>
            </ChatRouteGuard>
        );
        await waitFor(() => {
            expect(mockToast.error).toHaveBeenCalledWith('Chat not found or no longer available');
        });
        expect(mockNavigate).toHaveBeenCalledWith('/chat', { replace: true });
    });

    it('hides children once the story query errors', async () => {
        mockStoryQuery.isError = true;
        render(
            <QueryClientProvider client={queryClient}>
                <MemoryRouter initialEntries={['/story/xyz']}>
                    <Routes>
                        <Route path="/story/:storyId" element={<StoryRouteGuard storyId="xyz"><div>story content</div></StoryRouteGuard>} />
                        <Route path="/story" element={<div>story list</div>} />
                    </Routes>
                </MemoryRouter>
            </QueryClientProvider>
        );
        await waitFor(() => {
            expect(mockToast.error).toHaveBeenCalledWith('Story not found or no longer available');
        });
        expect(mockNavigate).toHaveBeenCalledWith('/story', { replace: true });
        expect(screen.queryByText('story content')).not.toBeInTheDocument();
    });
});

describe('NotFound', () => {
    it('renders the 404 hero with links to the hub', () => {
        render(
            <MemoryRouter initialEntries={['/nope']}>
                <NotFound />
            </MemoryRouter>
        );
        expect(screen.getByText('404')).toBeInTheDocument();
        expect(screen.getByText('Back to Hub')).toBeInTheDocument();
        expect(screen.getByText('Discover Models')).toBeInTheDocument();
    });
});