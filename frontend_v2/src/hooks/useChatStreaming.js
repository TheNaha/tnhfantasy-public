import { useEffect, useRef, useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { useWebSocket, EventTypes } from '../api/websocket';
import { getStreamingJob, setStreamingJob, clearStreamingJob } from './useStreamingJobs';
import { jobMetadata } from '../utils/jobStatus';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';

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

    // Stall watchdog.
    //
    // The story stream has had one since its first pass; chat never did, so a
    // provider that stopped mid-reply left "X is thinking..." on screen
    // indefinitely with no error and no escape — the user reloads, and the reply
    // that was paid for is gone with the cache. Story's wording ("Your story is
    // saved") deliberately does not carry over: a chat reply is NOT saved until
    // its world-integration consumer writes the Message row, so claiming it is
    // would be a lie at exactly the moment the user relies on it.
    const CHAT_STALL_MS = 300000;
    const stallTimerRef = useRef(null);

    const armStallTimer = useCallback(() => {
        if (stallTimerRef.current) window.clearTimeout(stallTimerRef.current);
        stallTimerRef.current = window.setTimeout(() => {
            const root = queryClient.getQueryCache().findAll({ queryKey: ['streaming', 'jobs'] });
            const ids = root.flatMap((q) => Object.keys(q.state?.data || {}));
            ids.forEach((eventId) => clearStreamingJob(queryClient, eventId));
            toast.error(
                'Generation stalled. No reply was saved — sending again will restart it.'
            );
        }, CHAT_STALL_MS);
    }, [queryClient]);

    const clearStallTimer = useCallback(() => {
        if (stallTimerRef.current) {
            window.clearTimeout(stallTimerRef.current);
            stallTimerRef.current = null;
        }
    }, []);

    useEffect(() => () => clearStallTimer(), [clearStallTimer]);

    // Arm when a job is created, so a stream that never produces a first token
    // is covered too — the first-token arm alone would only catch a stream that
    // stalls part-way.
    const lastArmedJobRef = useRef(null);
    useEffect(() => {
        const jobs = queryClient.getQueryCache().findAll({ queryKey: ['streaming', 'jobs'] });
        const streamed = jobs.flatMap((q) => Object.values(q.state?.data || {}));
        const running = streamed.filter((j) => j && j.status !== 'completed' && j.status !== 'failed');
        if (!running.length) return;
        const armedKey = running.map((j) => j.text || '').join('').length;
        if (lastArmedJobRef.current !== armedKey) {
            lastArmedJobRef.current = armedKey;
            armStallTimer();
        }
    }, [queryClient, armStallTimer]);

    useEffect(() => {
        const getJob = (event) => event?.data?.job || {};

        const pendingStream = new Map();
        let flushTimer = null;

        const applyStreamUpdate = (job) => {
            const streamText = job.text ?? job.message ?? null;
            const meta = jobMetadata(job);
            const eventId = job.id ?? null;

            const isSuggestion = eventId === suggestJobIdRef.current || !!meta.is_suggestion;
            if (isSuggestion) {
                if (streamText) setMessage(streamText);
                return;
            }

            // A background job must not render as a reply.
            //
            // Memory extraction runs after every reply, carries the same
            // `chat_id` (it is derived from that conversation), and streams
            // tokens — so this reducer produced a second "X is thinking…" bubble
            // under the reply it was extracted from. The backend marks such jobs
            // `background: true` in the workflow, which `job_metadata` copies
            // onto the event payload, and the terminal path drops them too.
            if (meta.background) return;

            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;
            if (eventChatId && (streamText != null || job.phase || job.status === 'evaluating_prompt')) {
                setStreamingJob(queryClient, eventId, {
                    text: streamText ?? existingJob?.text ?? '',
                    status: job.status || 'running',
                    phase: job.phase || (streamText ? 'generating' : 'evaluating_prompt'),
                    speedTps: job.speed_tps ?? meta.speed_tps ?? existingJob?.speedTps ?? null,
                    tokenCount: job.token_count ?? meta.token_count ?? existingJob?.tokenCount ?? 0,
                    elapsedSeconds: job.elapsed_seconds ?? existingJob?.elapsedSeconds ?? null,
                    providerId: job.provider_id ?? meta.provider_id ?? existingJob?.providerId ?? null,
                    model: job.model ?? meta.model ?? existingJob?.model ?? null,
                    chatId: eventChatId,
                    type: meta.workspace || existingJob?.type,
                    taskType: job.task_type ?? existingJob?.taskType ?? null,
                    progress: job.overall_progress ?? job.progress ?? null,
                    directorDecision: existingJob?.directorDecision || meta.context_trace?.director_decision || null,
                    contextTrace: existingJob?.contextTrace || meta.context_trace || null,
                });
                // Every token is proof of life. `armStallTimer` clears any
                // previous timer before setting a new one, so this is a reset
                // rather than a start — the watchdog is for a stream that STOPS
                // mid-reply, not for a slow provider.
                armStallTimer();
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
            const meta = jobMetadata(job);
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
            const meta = jobMetadata(job);
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
            const meta = jobMetadata(job);
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
            const meta = jobMetadata(job);
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

            // A background job completing must not refetch the transcript.
            //
            // Memory extraction carries the chat's own `chat_id`, so without
            // this its completion invalidated the whole message list a second
            // time per turn — a full refetch of the conversation after every
            // reply, for a job that added no message at all.
            if (meta.background) return;

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
                // A chat completion is also where memory extraction runs: the
                // backend scans the new exchange and writes character memories
                // after the reply is stored. The memories list was not
                // invalidated here, so a memory panel stayed stale until
                // navigation — the panel did not show what the turn had just
                // learned.
                //
                // Keyed on the CHARACTER, not the chat: the memories query is
                // `['world_vault','memories',characterId]`
                // (useMemories.js), so a chat id would prefix-match nothing
                // and "fix" it with a no-op.
                const memoryCharacterId = meta.character_id || existingJob?.characterId;
                if (memoryCharacterId) {
                    queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MEMORIES, memoryCharacterId), exact: true });
                }
            }

            if (eventChatId === activeChatId) {
                const jobType = meta.workspace || job.task_type;
                if (job.type === 'chat_tts') {
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

            // A suggest-reply completes with nothing persisted, so its only
            // client-visible end is this event — and until now there was no
            // branch here. `suggestJobId` was cleared on JOB_FAILED and nothing
            // else, so a SUCCESSFUL suggestion left the Suggest button disabled
            // until the 120s safety timer fired, even though the suggestion was
            // already sitting in the input box.
            if (eventId === suggestJobIdRef.current) {
                suggestJobIdRef.current = null;
                setSuggestJobId(null);
            }
        });

        const unsubError = subscribe(EventTypes.JOB_FAILED, (event) => {
            const job = getJob(event);
            const meta = jobMetadata(job);
            const eventId = job.id ?? null;
            if (eventId) pendingStream.delete(eventId);
            const existingJob = getStreamingJob(queryClient, eventId);
            const eventChatId = meta.chat_id || existingJob?.chatId;

            if (eventId === suggestJobIdRef.current) setSuggestJobId(null);
            if (eventId) clearStreamingJob(queryClient, eventId, eventChatId);

            if (eventChatId) {
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.MESSAGES, eventChatId) });
            }
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
            const meta = jobMetadata(job);
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
    }, [subscribe, activeChatId, queryClient, setMessage, setSuggestJobId, setSceneJobId, setIsGeneratingScene, suggestJobIdRef, sceneJobIdRef, armStallTimer, clearStallTimer]);
}
