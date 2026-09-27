import { useState, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { useWebSocket, EventTypes } from '../api/websocket';
import { clearStreamingJob } from './useStreamingJobs';

export function useStoryStreaming({
    activeStoryId,
    activeChapterId,
    setEditorContent,
    isDirtyRef
}) {
    const queryClient = useQueryClient();
    const { subscribe } = useWebSocket();

    const [isStreaming, setIsStreaming] = useState(false);
    const [isIllustrating, setIsIllustrating] = useState(false);
    
    const streamingRef = useRef('');
    const streamingBaseRef = useRef('');
    const isStreamingRef = useRef(false);
    const streamSafetyTimerRef = useRef(null);

    useEffect(() => {
        let active = true;
        queueMicrotask(() => {
            if (!active) return;
            setIsStreaming(false);
            setIsIllustrating(false);
            streamingRef.current = '';
            streamingBaseRef.current = '';
        });
        return () => {
            active = false;
        };
    }, [activeStoryId, activeChapterId]);

    // The safety timer belongs to the `isStreaming` effect below, which re-arms
    // it on every stream. Clearing it here used to leave a stream that started
    // before the reset microtask ran with no watchdog at all.
    useEffect(() => () => {
        if (streamSafetyTimerRef.current) {
            window.clearTimeout(streamSafetyTimerRef.current);
            streamSafetyTimerRef.current = null;
        }
    }, []);

    useEffect(() => {
        isStreamingRef.current = isStreaming;
    }, [isStreaming]);

    // WebSocket for streaming story continuation
    useEffect(() => {
        const getJob = (event) => event?.data?.job || {};

        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            if (meta.story_id === activeStoryId && meta.chapter_id === activeChapterId && meta.type === 'story_continue') {
                const streamText = job.text ?? job.message ?? null;
                if (streamText) {
                    setIsStreaming(true);
                    streamingRef.current = streamText;
                    setEditorContent(() => {
                        const baseContent = streamingBaseRef.current || '';
                        return baseContent ? baseContent + '\n\n' + streamText : streamText;
                    });
                }
            }
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, async (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            
            if (meta.type === 'story_parse' && meta.story_id === activeStoryId) {
                // A parse creates characters, locations and lorebooks (one
                // lorebook per location) and links them onto the story — see
                // `_handle_story_parse`. That is the whole blast radius: the
                // bare `['world_vault']` root used to refetch every cached chat,
                // persona, memory, scenario and relationship graph on top of it.
                ['characters', 'lorebooks', 'locations'].forEach((resource) => {
                    queryClient.invalidateQueries({ queryKey: ['world_vault', resource] });
                });
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId], exact: true });
                toast.success("Story parsed! Characters & lorebooks imported.");
                return;
            }
            
            if (meta.story_id === activeStoryId && meta.chapter_id === activeChapterId) {
                if (job.task_type === 'image' || meta.workspace === 'image') {
                    setIsIllustrating(false);
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'images'] });
                    toast.success('Illustration complete');
                } else if (meta.type === 'story_continue') {
                    const finalStreamedText = streamingRef.current;
                    streamingRef.current = '';
                    setIsStreaming(false);

                    setEditorContent(prev => {
                        const newBase = finalStreamedText
                            ? (streamingBaseRef.current ? streamingBaseRef.current + '\n\n' + finalStreamedText : finalStreamedText)
                            : prev;
                        streamingBaseRef.current = newBase;
                        return newBase;
                    });

                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] }).then(() => {
                        if (isDirtyRef.current) return;
                        const data = queryClient.getQueryData(['world_vault', 'stories', activeStoryId, 'chapters']);
                        const freshChapter = Array.isArray(data) ? data.find(ch => ch.id === activeChapterId) : null;
                        if (freshChapter?.content && freshChapter.content !== (streamingBaseRef.current || '')) {
                            setEditorContent(freshChapter.content);
                            streamingBaseRef.current = freshChapter.content;
                        }
                    });
                    if (job.id) clearStreamingJob(queryClient, job.id);
                }
            }
        });

        const unsubFailed = subscribe(EventTypes.JOB_FAILED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            if (meta.story_id === activeStoryId && meta.chapter_id === activeChapterId) {
                setIsStreaming(false);
                setIsIllustrating(false);
                streamingRef.current = '';
                toast.error('Job failed: ' + (job.error || 'Unknown error'));
                if (job.id) clearStreamingJob(queryClient, job.id);
            }
        });

        const unsubCancelled = subscribe(EventTypes.JOB_CANCELLED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            if (meta.story_id === activeStoryId && meta.chapter_id === activeChapterId) {
                setIsStreaming(false);
                setIsIllustrating(false);
                streamingRef.current = '';
                if (job.id) clearStreamingJob(queryClient, job.id);
            }
        });

        return () => {
            unsubProgress();
            unsubCompleted();
            unsubFailed();
            unsubCancelled();
        };
    }, [subscribe, activeStoryId, activeChapterId, queryClient, setEditorContent, isDirtyRef]);

    useEffect(() => {
        if (!isStreaming) return;
        streamSafetyTimerRef.current = window.setTimeout(() => {
            setIsStreaming(false);
            setIsIllustrating(false);
            streamingRef.current = '';
            toast.error('Connection lost — streaming stopped. Your story is saved.');
        }, 300000);
        return () => {
            if (streamSafetyTimerRef.current) {
                window.clearTimeout(streamSafetyTimerRef.current);
                streamSafetyTimerRef.current = null;
            }
        };
    }, [isStreaming]);

    return {
        isStreaming,
        setIsStreaming,
        isIllustrating,
        setIsIllustrating,
        streamingBaseRef,
        isStreamingRef
    };
}
