import React from 'react';
import { act, cleanup, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const wsMock = vi.hoisted(() => {
    const handlers = new Map();
    return {
        handlers,
        subscribe: vi.fn((event, callback) => {
            if (!handlers.has(event)) handlers.set(event, new Set());
            handlers.get(event).add(callback);
            return () => handlers.get(event)?.delete(callback);
        }),
        emit(event, payload) {
            for (const cb of handlers.get(event) || []) cb(payload);
        },
    };
});

const toastMock = vi.hoisted(() => {
    const fn = vi.fn(() => undefined);
    fn.success = vi.fn();
    fn.error = vi.fn();
    fn.loading = vi.fn();
    return fn;
});

vi.mock('../api/websocket', () => ({
    useWebSocket: () => ({ subscribe: wsMock.subscribe }),
    EventTypes: {
        JOB_PROGRESS: 'job.progress',
        JOB_COMPLETED: 'job.completed',
        JOB_FAILED: 'job.failed',
        JOB_CANCELLED: 'job.cancelled',
    },
}));

vi.mock('react-hot-toast', () => ({ default: toastMock }));

import toast from 'react-hot-toast';
import { useChatStreaming } from './useChatStreaming';
import { setStreamingJob } from './useStreamingJobs';

function createQueryClient() {
    return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function createWrapper(qc) {
    return ({ children }) =>
        React.createElement(QueryClientProvider, { client: qc }, children);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function renderChatStreaming(qc, overrides = {}) {
    const setMessage = vi.fn();
    const setSuggestJobId = vi.fn();
    const setSceneJobId = vi.fn();
    const setIsGeneratingScene = vi.fn();
    const suggestJobIdRef = { current: null };
    const sceneJobIdRef = { current: null };

    const hook = renderHook(
        () =>
            useChatStreaming({
                activeChatId: 'chat-1',
                suggestJobIdRef,
                setMessage,
                setSuggestJobId,
                sceneJobIdRef,
                setSceneJobId,
                setIsGeneratingScene,
                ...overrides,
            }),
        { wrapper: createWrapper(qc) }
    );

    return { hook, setMessage, setSuggestJobId, setSceneJobId, setIsGeneratingScene, suggestJobIdRef, sceneJobIdRef };
}

describe('useChatStreaming', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
        wsMock.handlers.clear();
    });

    afterEach(() => cleanup());

    it('streams progress text into the streaming-job cache for chat jobs', async () => {
        const qc = createQueryClient();
        renderChatStreaming(qc);

        await act(async () => {
            wsMock.emit('job.progress', {
                data: {
                    job: {
                        id: 'job-1',
                        task_type: 'llm',
                        text: 'Once upon',
                        metadata_: { chat_id: 'chat-1', workspace: 'chat' },
                    },
                },
            });
            await sleep(150); // flush the 100ms throttle
        });

        expect(qc.getQueryData(['streaming', 'job-1'])).toEqual({
            text: 'Once upon',
            status: 'running',
            chatId: 'chat-1',
            type: 'chat',
            taskType: 'llm',
            progress: null,
            phase: 'generating',
            tokenCount: 0,
            speedTps: null,
            elapsedSeconds: null,
            model: null,
            providerId: null,
        });
    });

    it('routes suggestion job progress straight to setMessage', async () => {
        const qc = createQueryClient();
        const { suggestJobIdRef, setMessage } = renderChatStreaming(qc);
        suggestJobIdRef.current = 'job-sug';

        await act(async () => {
            wsMock.emit('job.progress', {
                data: { job: { id: 'job-sug', text: 'suggested reply' } },
            });
            await sleep(150); // flush the 100ms throttle
        });

        expect(setMessage).toHaveBeenCalledWith('suggested reply');
        expect(qc.getQueryData(['streaming', 'job-sug'])).toBeUndefined();
    });

    it('clears the stream, invalidates chat queries and toasts image success on completion', async () => {
        const qc = createQueryClient();
        const invalidate = vi.spyOn(qc, 'invalidateQueries');
        setStreamingJob(qc, 'job-img', { text: 'x', chatId: 'chat-1' });
        renderChatStreaming(qc);

        await act(async () => {
            wsMock.emit('job.completed', {
                data: {
                    job: {
                        id: 'job-img',
                        task_type: 'image',
                        outputs: [{ content: 'out.png' }],
                        metadata_: { chat_id: 'chat-1', image_context: true },
                    },
                },
            });
        });

        expect(qc.getQueryData(['streaming', 'job-img'])).toBeUndefined();
        expect(qc.getQueryData(['streaming', 'active', 'chat-1'])).toEqual([]);
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'messages', 'chat-1'] });
        // exact: the chat *detail* is what a completed job changes. Prefix
        // matching also dragged the system-prompt, jobs, images and branches
        // sub-queries on every job event, and the system-prompt refetch is the
        // expensive one (character + lorebook + world state assembly).
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'chat-1'], exact: true });
        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'chats', 'chat-1', 'images'], exact: true });
        expect(toast.success).toHaveBeenCalledWith('Image generated!', { icon: '🖼️' });
    });

    it('resolves chatId from the cached stream when the event has no metadata', async () => {
        const qc = createQueryClient();
        setStreamingJob(qc, 'job-1', { text: 'x', chatId: 'chat-1' });
        const invalidate = vi.spyOn(qc, 'invalidateQueries');
        renderChatStreaming(qc);

        await act(async () => {
            wsMock.emit('job.completed', {
                data: { job: { id: 'job-1', task_type: 'llm', outputs: [] } },
            });
        });

        expect(invalidate).toHaveBeenCalledWith({ queryKey: ['world_vault', 'messages', 'chat-1'] });
    });

    it('finishes suggestion jobs with the output text and resets the suggestion id', async () => {
        const qc = createQueryClient();
        const { suggestJobIdRef, setMessage, setSuggestJobId } = renderChatStreaming(qc);
        suggestJobIdRef.current = 'job-sug';

        await act(async () => {
            wsMock.emit('job.completed', {
                data: {
                    job: {
                        id: 'job-sug',
                        task_type: 'llm',
                        outputs: [{ content: 'final suggestion' }],
                        metadata_: { is_suggestion: true },
                    },
                },
            });
        });

        expect(setMessage).toHaveBeenCalledWith('final suggestion');
        expect(setSuggestJobId).toHaveBeenCalledWith(null);
    });

    it('resets scene state when the scene job completes', async () => {
        const qc = createQueryClient();
        const { sceneJobIdRef, setSceneJobId, setIsGeneratingScene } = renderChatStreaming(qc);
        sceneJobIdRef.current = 'job-scene';

        await act(async () => {
            wsMock.emit('job.completed', {
                data: {
                    job: {
                        id: 'job-scene',
                        task_type: 'image',
                        outputs: [],
                        metadata_: { image_context: true },
                    },
                },
            });
        });

        expect(sceneJobIdRef.current).toBeNull();
        expect(setSceneJobId).toHaveBeenCalledWith(null);
        expect(setIsGeneratingScene).toHaveBeenCalledWith(false);
    });

    it('shows an error toast for failed jobs in the active chat', async () => {
        const qc = createQueryClient();
        renderChatStreaming(qc);

        await act(async () => {
            wsMock.emit('job.failed', {
                data: { job: { id: 'job-1', metadata_: { chat_id: 'chat-1' } } },
            });
        });

        expect(toast.error).toHaveBeenCalledWith('AI response failed. Please try again.');
    });

    it('shows a cancel toast for cancelled jobs in the active chat', async () => {
        const qc = createQueryClient();
        renderChatStreaming(qc);

        await act(async () => {
            wsMock.emit('job.cancelled', {
                data: { job: { id: 'job-1', metadata_: { chat_id: 'chat-1' } } },
            });
        });

        expect(toast).toHaveBeenCalledWith('AI response cancelled', { icon: '🛑' });
    });

    it('does not toast failures from other chats', async () => {
        const qc = createQueryClient();
        renderChatStreaming(qc);

        await act(async () => {
            wsMock.emit('job.failed', {
                data: { job: { id: 'job-1', metadata_: { chat_id: 'chat-other' } } },
            });
        });

        expect(toast.error).not.toHaveBeenCalled();
    });

    it('unsubscribes from all four event channels on unmount', async () => {
        const qc = createQueryClient();
        const { hook } = renderChatStreaming(qc);
        const events = ['job.progress', 'job.completed', 'job.failed', 'job.cancelled'];
        expect(events.every((e) => wsMock.handlers.get(e)?.size === 1)).toBe(true);

        hook.unmount();
        expect(events.every((e) => (wsMock.handlers.get(e)?.size ?? 0) === 0)).toBe(true);
    });
});