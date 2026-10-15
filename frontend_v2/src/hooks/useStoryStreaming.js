import { useState, useRef, useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { useWebSocket, EventTypes } from '../api/websocket';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { clearStreamingJob } from './useStreamingJobs';
import { jobMetadata } from '../utils/jobStatus';

const STORY_CHAPTERS_KEY = (storyId) => buildQueryKey(QUERY_KEYS.STORIES, storyId, 'chapters');

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

    // Stream-write throttle. Chat has had one since its first pass; story never
    // did, so a chapter continuation re-rendered the editor once per token.
    const STREAM_WRITE_MS = 100;
    const streamWriteAtRef = useRef(0);
    const streamPendingRef = useRef(false);


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

        // Write the latest streamed text, yielding to a human. Defined here
        // rather than at the top because it closes over `setEditorContent`,
        // which is a prop, and a stable identity for it buys nothing.
        const writeStreamContent = (streamText) => {
            let userTookOver = false;
            setEditorContent((prev) => {
                const baseContent = streamingBaseRef.current || '';
                const expected = baseContent ? baseContent + '\n\n' + streamText : streamText;
                userTookOver = prev !== expected;
                if (userTookOver) return prev;
                return expected;
            });
        };

        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            const job = getJob(event);
            const meta = jobMetadata(job);
            if (meta.story_id === activeStoryId && meta.chapter_id === activeChapterId && meta.type === 'story_continue') {
                const streamText = job.text ?? job.message ?? null;
                if (streamText) {
                    setIsStreaming(true);
                    streamingRef.current = streamText;

                    // Yield to the user. The editor used to be `disabled` for the
                    // whole stream, so the one moment you most want to change a
                    // sentence is the one moment the box is frozen. It is editable
                    // now, which means the stream has to stop overwriting a
                    // human: once the editor no longer holds exactly what the
                    // stream last wrote, the user has typed, and the remaining
                    // tokens stop landing in the text.
                    //
                    // Detected by shape rather than a new flag threaded through
                    // the editor — the editor is the source of truth and this is
                    // the only writer, so a mismatch is by definition a user edit.
                    // Throttled, because the editor re-rendered on EVERY token.
                    // `setEditorContent` rewrites the whole chapter textarea and
                    // the author-note effect reads it, so one call per token at
                    // 40 tok/s meant 40 full editor renders per second — and the
                    // 2000 ms autosave debounce was contended against each of
                    // them. Chat has throttled at 100 ms since its first pass;
                    // story never did.
                    const throttledAt = streamWriteAtRef.current;
                    const now = Date.now();
                    if (throttledAt && now - throttledAt < STREAM_WRITE_MS) {
                        streamPendingRef.current = true;
                    } else {
                        streamWriteAtRef.current = now;
                        writeStreamContent(streamText);
                    }
                }
            }
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, async (event) => {
            const job = getJob(event);
            const meta = jobMetadata(job);
            
            if (meta.type === 'story_parse' && meta.story_id === activeStoryId) {
                // A parse creates characters, locations and lorebooks (one
                // lorebook per location) and links them onto the story — see
                // `_handle_story_parse`. That is the whole blast radius: the
                // bare `['world_vault']` root used to refetch every cached chat,
                // persona, memory, scenario and relationship graph on top of it.
                [QUERY_KEYS.CHARACTERS, QUERY_KEYS.LOREBOOKS, QUERY_KEYS.LOCATIONS].forEach((resource) => {
                    queryClient.invalidateQueries({ queryKey: buildQueryKey(resource) });
                });
                queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId), exact: true });
                toast.success("Story parsed! Characters & lorebooks imported.");
                return;
            }
            
            if (meta.story_id === activeStoryId && meta.chapter_id === activeChapterId) {
                // Chapter illustration is TWO chained paid jobs: an LLM writes
                // the art direction, then that output drives an image job. The
                // user sees one spinner for both, with nothing to say which of
                // the two is running or that the second one has begun. Naming the
                // handover is what makes the dead middle of that wait legible.
                if (meta.type === 'story_illustrate_prompt') {
                    toast('Art direction ready — generating the image...', { icon: '🎨' });
                }
                if (job.task_type === 'image') {
                    setIsIllustrating(false);
                    queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(activeStoryId) });
                    queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'images') });
                    toast.success('Illustration complete');
                } else if (job.task_type === 'tts') {
                    // Narration completes invisibly without this.
                    //
                    // The TTS job writes `chapter.beats` with an `audio_path`
                    // (world_integration_service._handle_story_tts), but this
                    // handler only matched `image` and `story_continue`. So the
                    // beat never re-rendered until some OTHER query happened to
                    // refetch the chapter — navigation, a chapter switch, a later
                    // invalidation — which made narration look like it had done
                    // nothing at all.
                    queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(activeStoryId) });
                    queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'beats') });
                    toast.success('Narration ready');
                } else if (meta.type === 'story_continue') {
                    const finalStreamedText = streamingRef.current;
                    streamingRef.current = '';
                    // Flush a write the throttle held back. Without this the
                    // last partial second of tokens was dropped: the throttled
                    // handler updates `streamingRef` but only writes the editor on
                    // the next pass, and completion is the last pass.
                    if (streamPendingRef.current && finalStreamedText) {
                        streamPendingRef.current = false;
                        streamWriteAtRef.current = 0;
                        writeStreamContent(finalStreamedText);
                    }
                    setIsStreaming(false);

                    setEditorContent(prev => {
                        const newBase = finalStreamedText
                            ? (streamingBaseRef.current ? streamingBaseRef.current + '\n\n' + finalStreamedText : finalStreamedText)
                            : prev;
                        streamingBaseRef.current = newBase;
                        return newBase;
                    });

                    queryClient.invalidateQueries({ queryKey: STORY_CHAPTERS_KEY(activeStoryId) }).then(() => {
                        if (isDirtyRef.current) return;
                        const data = queryClient.getQueryData(STORY_CHAPTERS_KEY(activeStoryId));
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
            const meta = jobMetadata(job);
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
            const meta = jobMetadata(job);
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

    // One watchdog for both waits, because they are two different states with
    // the same failure shape and only one of them used to be covered.
    //
    // `isStreaming` always had this. `isIllustrating` did not, and it needed it
    // more: an illustration started with a supplied prompt never streams, so
    // `isStreaming` stays false and the timer never armed. Every way that wait
    // can end silently leaves the button spinning until a full page reload —
    // the art-direction job returning empty text (its handler returns without
    // producing an image job), the chain failing, or the event bus dropping the
    // JOB_COMPLETED. So the two states are guarded together, with a message that
    // names which one stalled.
    const waitingOn = isStreaming ? 'stream' : isIllustrating ? 'illustration' : null;

    useEffect(() => {
        if (!waitingOn) return;
        streamSafetyTimerRef.current = window.setTimeout(() => {
            const stalled = waitingOn;
            setIsStreaming(false);
            setIsIllustrating(false);
            streamingRef.current = '';
            if (stalled === 'stream') {
                toast.error('Connection lost — streaming stopped. Your story is saved.');
            } else {
                // Not the same message, and deliberately not "your story is
                // saved": nothing was written, and the spent job is the point.
                toast.error(
                    'Illustration never reported back. It may still be running — check the Jobs page before retrying, or you will pay for it twice.',
                    { duration: 8000 }
                );
            }
        }, 300000);
        return () => {
            if (streamSafetyTimerRef.current) {
                window.clearTimeout(streamSafetyTimerRef.current);
                streamSafetyTimerRef.current = null;
            }
        };
    }, [waitingOn]);

    return {
        isStreaming,
        setIsStreaming,
        isIllustrating,
        setIsIllustrating,
        streamingBaseRef,
        isStreamingRef
    };
}
