import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { useWebSocket, EventTypes } from '../api/websocket';
import { getStreamingJob, setStreamingJob, clearStreamingJob } from './useStreamingJobs';

export function useChatStreaming({
    activeChatId,
    suggestJobIdRef,
    setMessage,
    setSuggestJobId,
    sceneJobIdRef,
    setSceneJobId,
    setIsGeneratingScene
}) {
    const queryClient = useQueryClient();
    const { subscribe } = useWebSocket();

    useEffect(() => {
        const getJob = (event) => event?.data?.job || {};

        const pendingStream = new Map();
        let flushTimer = null;

        const applyStreamUpdate = (job) => {
            const streamText = job.text ?? job.message ?? null;
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;

            const isSuggestion = eventId === suggestJobIdRef.current || !!meta.is_suggestion;
            if (isSuggestion) {
                if (streamText) setMessage(streamText);
                return;
            }

            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;
            if (streamText && eventChatId) {
                setStreamingJob(queryClient, eventId, {
                    text: streamText,
                    status: 'running',
                    chatId: eventChatId,
                    type: meta.workspace,
                    taskType: job.task_type ?? null,
                    progress: job.overall_progress ?? job.progress ?? null
                });
            }
        };

        const throttleProgress = (job) => {
            const eventId = job.id ?? null;
            if (!eventId) { applyStreamUpdate(job); return; }
            pendingStream.set(eventId, job);
            if (flushTimer) return;
            flushTimer = setTimeout(() => {
                flushTimer = null;
                for (const [, pendingJob] of pendingStream) applyStreamUpdate(pendingJob);
                pendingStream.clear();
            }, 100);
        };

        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            throttleProgress(getJob(event));
        });

        const unsubCreated = subscribe(EventTypes.JOB_CREATED, (event) => {
            const job = getJob(event);
            const meta = job.metadata ?? job.metadata_ ?? {};
            const eventId = job.id ?? null;
            if (!eventId) return;

            // No-op if we are already tracking this job.
            const existing = getStreamingJob(queryClient, eventId);
            if (existing) return;

            const eventChatId = meta.chat_id || null;
            setStreamingJob(queryClient, eventId, {
                status: 'queued',
                chatId: eventChatId,
                type: meta.workspace,
                taskType: job.task_type ?? null,
                progress: job.overall_progress ?? job.progress ?? null
            });
        });

        const unsubUpdated = subscribe(EventTypes.JOB_UPDATED, (event) => {
            const job = getJob(event);
            const meta = job.metadata ?? job.metadata_ ?? {};
            const eventId = job.id ?? null;
            if (!eventId) return;

            const existing = getStreamingJob(queryClient, eventId);
            if (!existing) return;

            // Merge status/metadata updates without clobbering progress.
            setStreamingJob(queryClient, eventId, {
                status: job.status ?? existing.status,
                chatId: meta.chat_id || existing.chatId,
                type: existing.type ?? meta.workspace,
                taskType: job.task_type ?? existing.taskType,
                progress: existing.progress ?? job.overall_progress ?? job.progress ?? null
            });
        });

        const unsubPostProcessing = subscribe(EventTypes.JOB_POST_PROCESSING, (event) => {
            const job = getJob(event);
            const meta = job.metadata ?? job.metadata_ ?? {};
            const eventId = job.id ?? null;
            if (!eventId) return;

            const existing = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existing?.chatId;

            // Reflect the post-process phase instead of hanging on "Preparing generation…".
            const phase = job.phase ?? meta.phase ?? null;
            const statusText = phase === 'upload' ? 'Uploading…' : 'Saving…';

            // Do not reset progress on this event.
            const progress = job.overall_progress ?? job.progress ?? existing?.progress ?? null;

            setStreamingJob(queryClient, eventId, {
                status: statusText,
                chatId: eventChatId,
                type: existing?.type ?? meta.workspace,
                taskType: job.task_type ?? existing?.taskType ?? null,
                progress
            });
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;

            if (eventId) pendingStream.delete(eventId);

            const isSuggestion = eventId === suggestJobIdRef.current || !!meta.is_suggestion;
            if (isSuggestion) {
                const outputText = job.outputs?.[0]?.content ?? null;
                if (outputText) setMessage(outputText);
                setSuggestJobId(null);
                return;
            }

            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId) {
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'messages', eventChatId] });
                // `exact: true` is load-bearing. The 3-element chat key is a
                // *prefix* of the sub-queries
                // (['world_vault','chats',id,'system-prompt' | 'jobs' |
                // 'images' | 'branches']), so a plain invalidation refetched
                // the full system-prompt assembly — character + lorebook +
                // world state, plus the last MAX_CONTEXT_MESSAGES messages —
                // after every completed chat job, for a payload the completion
                // event cannot change. The jobs and images lists are named
                // explicitly below because they are the sub-queries that do
                // move when a job finishes.
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', eventChatId], exact: true });
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', eventChatId, 'jobs'], exact: true });
                if (job.task_type === 'image') {
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'chats', eventChatId, 'images'], exact: true });
                }
            }

            if (eventChatId === activeChatId) {
                const jobType = meta.workspace || job.task_type;
                if (meta.type === 'chat_tts') {
                    toast.success('Speech generated!', { icon: '🎤' });
                } else if (jobType === 'image' || meta.image_context) {
                    toast.success('Image generated!', { icon: '🖼️' });
                }
            }

            if (eventId === sceneJobIdRef.current) {
                sceneJobIdRef.current = null;
                setSceneJobId(null);
                setIsGeneratingScene(false);
            }
        });

        const unsubError = subscribe(EventTypes.JOB_FAILED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;
            if (eventId) pendingStream.delete(eventId);
            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId === suggestJobIdRef.current) setSuggestJobId(null);
            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId === activeChatId) {
                toast.error('AI response failed. Please try again.');
            }

            if (eventId === sceneJobIdRef.current) {
                sceneJobIdRef.current = null;
                setSceneJobId(null);
                setIsGeneratingScene(false);
            }
        });

        const unsubCancelled = subscribe(EventTypes.JOB_CANCELLED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const eventId = job.id ?? null;
            if (eventId) pendingStream.delete(eventId);
            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId === suggestJobIdRef.current) setSuggestJobId(null);
            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId === activeChatId) {
                toast('AI response cancelled', { icon: '🛑' });
            }
        });

        return () => {
            if (flushTimer) clearTimeout(flushTimer);
            pendingStream.clear();
            unsubProgress(); unsubCompleted(); unsubError(); unsubCancelled();
            unsubCreated(); unsubUpdated(); unsubPostProcessing();
        };
    }, [subscribe, activeChatId, queryClient, setMessage, setSuggestJobId, setSceneJobId, setIsGeneratingScene, suggestJobIdRef, sceneJobIdRef]);
}
