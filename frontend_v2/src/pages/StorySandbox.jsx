import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useParams, useNavigate } from 'react-router-dom';
import { BookOpen, Sparkles, Image as ImageIcon, Save, Undo2, Play, Settings, Type, Plus, Loader2, Trash2, ChevronRight, Edit3, Book, Layers, Check, Columns, X, Clock, MapPin, PenTool, Calendar, Tag, GitBranch } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useStories, useStory, useStoryChapters, useCreateStory, useCreateChapter, useContinueChapter, useBranchChapter, useAddStoryBeat, useLorebooks, useCharacters, useDeleteStory, useDeleteChapter, useUpdateChapter, useUpdateStory, useIllustrateChapter, useLLMAvailableModels, useLLMDefaultProvider, useStoryImages } from '../hooks/useWorldVault';
import { useLLMJobResult } from '../hooks/useLLMJobResult';
import { api } from '../api';
import { assetUrl } from '../utils/assetUrl';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useQueryClient } from '@tanstack/react-query';
import { clearStreamingJob } from '../hooks/useStreamingJobs';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';
import { useCollections } from '../hooks/useCollections';
import { addImagesToCollection } from '../api/collectionsApi';
import SceneGallery from '../components/SceneGallery';
import BottomTabBar from '../components/BottomTabBar';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const StorySidebar = React.memo(function StorySidebar({ stories, activeStoryId, onSelectStory, onCreateStory, onDeleteStory, isLoading }) {
    const [creating, setCreating] = useState(false);
    const [newTitle, setNewTitle] = useState('');

    const handleCreate = async () => {
        if (!newTitle.trim()) return;
        setCreating(true);
        try {
            await onCreateStory({ title: newTitle.trim() });
            setNewTitle('');
            toast.success('Story created');
        } catch {
            toast.error('Failed to create story');
        }
        setCreating(false);
    };

    return (
        <div className="flex flex-col shrink-0 min-h-0 flex-1">
            <div className="h-16 flex items-center justify-between px-4 border-b border-white/5 shrink-0">
                <h3 className="font-semibold text-gray-200">Stories</h3>
            </div>
            <div className="p-2 border-b border-white/5">
                <div className="flex gap-1">
                    <input
                        type="text"
                        value={newTitle}
                        onChange={e => setNewTitle(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                        placeholder="New story title..."
                        className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-1.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                        disabled={creating}
                    />
                    <button onClick={handleCreate} disabled={creating || !newTitle.trim()} className="p-1.5 text-gray-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors disabled:opacity-30">
                        <Plus size={18} />
                    </button>
                </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {isLoading ? (
                    <div className="flex justify-center p-4"><Loader2 className="animate-spin text-gray-500" /></div>
                ) : stories?.length === 0 ? (
                    <p className="text-xs text-gray-500 text-center p-4">No stories yet. Create one above.</p>
                ) : (
                    stories?.map(story => (
                        <div key={story.id} className="group relative">
                            <button
                                onClick={() => onSelectStory(story.id)}
                                className={clsx(
                                    "w-full text-left px-3 py-2 rounded-lg text-sm transition-colors flex items-center justify-between",
                                    activeStoryId === story.id ? "bg-indigo-500/20 text-indigo-300" : "text-gray-400 hover:bg-white/5"
                                )}
                            >
                                <span className="truncate flex-1">{story.title}</span>
                                {story.genre && <span className="text-[10px] text-gray-500 ml-2 shrink-0">{story.genre}</span>}
                            </button>
                            <button
                                onClick={(e) => { e.stopPropagation(); onDeleteStory(story); }}
                                className="absolute right-1 top-1 p-1 opacity-0 group-hover:opacity-100 hover:text-red-400 text-gray-500 rounded transition-all"
                                title="Delete story"
                            >
                                <Trash2 size={12} />
                            </button>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
});

const ChapterSidebar = React.memo(function ChapterSidebar({ chapters, activeChapterId, onSelectChapter, onCreateChapter, onDeleteChapter, isLoading }) {
    const [creating, setCreating] = useState(false);

    const handleCreate = async () => {
        setCreating(true);
        try {
            await onCreateChapter({ title: `Chapter ${(chapters?.length || 0) + 1}` });
            toast.success('Chapter created');
        } catch {
            toast.error('Failed to create chapter');
        }
        setCreating(false);
    };

    return (
        <div className="w-full border-t border-white/5 bg-gray-900/40 flex flex-col shrink-0 max-h-72 min-h-0">
            <div className="h-12 flex items-center justify-between px-3 border-b border-white/5 shrink-0">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Chapters</h4>
                <button onClick={handleCreate} disabled={creating} className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded transition-colors disabled:opacity-30" title="New chapter">
                    <Plus size={14} />
                </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1 min-h-0">
                {isLoading ? (
                    <div className="flex justify-center p-3"><Loader2 className="animate-spin text-gray-500" size={14} /></div>
                ) : chapters?.length === 0 ? (
                    <p className="text-[11px] text-gray-500 text-center p-3">No chapters yet</p>
                ) : (
                    chapters?.map(ch => (
                        <div key={ch.id} className="group relative">
                            <button
                                onClick={() => onSelectChapter(ch.id)}
                                className={clsx(
                                    "w-full text-left px-2 py-1.5 rounded text-xs transition-colors flex items-center gap-1.5",
                                    activeChapterId === ch.id ? "bg-indigo-500/20 text-indigo-300" : "text-gray-400 hover:bg-white/5"
                                )}
                            >
                                <span className="font-mono text-[10px] text-gray-500">{ch.chapter_number}</span>
                                <span className="truncate">{ch.title || `Chapter ${ch.chapter_number}`}</span>
                            </button>
                            {onDeleteChapter && (
                                <button
                                    onClick={(e) => { e.stopPropagation(); onDeleteChapter(ch.id); }}
                                    className="absolute right-1 top-1 p-1 opacity-0 group-hover:opacity-100 hover:text-red-400 text-gray-500 rounded transition-all"
                                    title="Delete chapter"
                                >
                                    <Trash2 size={10} />
                                </button>
                            )}
                        </div>
                    ))
                )}
            </div>
        </div>
    );
});

export default function StorySandbox() {
    // Only default the context panel open on desktop — on phones/tablets the
    // panel is an overlay tab, so don't mount (and animate) it on every visit.
    const [isPanelOpen, setIsPanelOpen] = useState(() => typeof window !== 'undefined' && window.innerWidth >= 1024);
    const [editorContent, setEditorContent] = useState('');
    const [beatInput, setBeatInput] = useState('');
    const textareaRef = useRef(null);
    const streamingRef = useRef('');
    const streamingBaseRef = useRef('');
    const loadedChapterIdRef = useRef(null);

    const queryClient = useQueryClient();
    const { storyId: urlStoryId, chapterId: urlChapterId } = useParams();
    const navigate = useNavigate();
    const activeStoryId = urlStoryId || null;
    const activeChapterId = urlChapterId || null;

    const { data: stories = [], isLoading: storiesLoading } = useStories();
    const { data: activeStory } = useStory(activeStoryId);
    const { data: chapters = [], isLoading: chaptersLoading } = useStoryChapters(activeStoryId);
    const { data: lorebooks = [] } = useLorebooks();
    const { data: characters = [] } = useCharacters();
    const { data: storyImages = [] } = useStoryImages(activeStoryId);
    const { data: collectionsMap = {} } = useCollections('story');
    const collectionsList = Object.values(collectionsMap).sort((a, b) => (a.name || '').localeCompare(b.name || ''));

    const createStory = useCreateStory();
    const createChapter = useCreateChapter();
    const continueChapter = useContinueChapter();
    const branchChapter = useBranchChapter();
    const addStoryBeat = useAddStoryBeat();
    const deleteStory = useDeleteStory();
    const deleteChapter = useDeleteChapter();
    const updateChapter = useUpdateChapter();
    const illustrateChapter = useIllustrateChapter();

    const [isStreaming, setIsStreaming] = useState(false);
    // Keep a ref in sync so WebSocket handlers can read the live value
    // without being listed in effect deps (avoids re-registering on every render).
    const isStreamingRef = useRef(false);
    useEffect(() => { isStreamingRef.current = isStreaming; }, [isStreaming]);
    // Safety net: if the terminal WS event is missed (reconnect gap, WS down),
    // don't leave Continue/textarea/Save locked forever. LLM jobs time out at
    // 180s and image jobs well under 5 min, so this only fires on real gaps.
    const streamSafetyTimerRef = useRef(null);

    const [illustratePrompt, setIllustratePrompt] = useState('');
    const [showIllustrateModal, setShowIllustrateModal] = useState(false);
    const [isIllustrating, setIsIllustrating] = useState(false);
    const [showGallery, setShowGallery] = useState(false);
    const [isPreviewMode, setIsPreviewMode] = useState(false);
    const [showBeatsPanel, setShowBeatsPanel] = useState(false);
    const [branchingBeatId, setBranchingBeatId] = useState(null);
    const [mobileTab, setMobileTab] = useState('write'); // 'stories' | 'chapters' | 'write' | 'context'
    const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
    // True once the user manually edits the editor — suppresses server-pushed
    // content updates (post-refetch sync) so typing is never clobbered.
    const isDirtyRef = useRef(false);
    // Cancels the 30x1s title-generation poll when navigating away.
    const titlePollCancelledRef = useRef(false);

    useEffect(() => {
        titlePollCancelledRef.current = true;
    }, [activeChapterId]);

    const { data: llmModels = [] } = useLLMAvailableModels();
    const { data: defaultLlmConfig } = useLLMDefaultProvider();
    const updateStory = useUpdateStory();

    const { subscribe } = useWebSocket();
    const runLLMJob = useLLMJobResult();
    const { confirm } = useConfirmation();

    const activeChapter = chapters?.find(ch => ch.id === activeChapterId);

    // Auto-select first story
    useEffect(() => {
        if (stories?.length > 0 && !activeStoryId) {
            navigate(`/story/${stories[0].id}`, { replace: true });
        }
    }, [stories, activeStoryId, navigate]);

    // Auto-select first chapter
    useEffect(() => {
        if (chapters?.length > 0 && activeStoryId && !activeChapterId) {
            // Wait for next tick to avoid synchronous cascading renders
            const timer = setTimeout(() => navigate(`/story/${activeStoryId}/chapter/${chapters[0].id}`, { replace: true }), 0);
            return () => clearTimeout(timer);
        }
    }, [chapters, activeStoryId, activeChapterId, navigate]);

    // Load chapter content into editor
    useEffect(() => {
        // Guard: don't overwrite editor content while actively streaming
        if (isStreamingRef.current) return;
        
        if (activeChapter && loadedChapterIdRef.current !== activeChapterId) {
            loadedChapterIdRef.current = activeChapterId;
            isDirtyRef.current = false;
            // Wait for next tick to avoid synchronous cascading renders
            const timer = setTimeout(() => {
                setEditorContent(activeChapter.content || '');
                streamingRef.current = '';
                streamingBaseRef.current = activeChapter.content || '';
            }, 0);
            return () => clearTimeout(timer);
        }
    }, [activeChapterId, activeChapter]);

    // WebSocket for streaming story continuation
    useEffect(() => {
        const getJob = (event) => event?.data?.job || {};

        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const storyId = meta.story_id;
            const chapterId = meta.chapter_id;
            
            if (storyId === activeStoryId && chapterId === activeChapterId) {
                const streamText = job.text ?? job.message ?? null;
                if (streamText) {
                    setIsStreaming(true);
                    streamingRef.current = streamText;
                    // Show accumulated text in editor while generating.
                    // Use streamingBaseRef (set at generation start) to avoid
                    // capturing the stale editorContent closure value.
                    setEditorContent(() => {
                        const baseContent = streamingBaseRef.current || '';
                        return baseContent ? baseContent + '\n\n' + streamText : streamText;
                    });
                }
            }
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const storyId = meta.story_id;
            const chapterId = meta.chapter_id;
            const eventType = job.task_type || meta.workspace;
            
            if (storyId === activeStoryId && chapterId === activeChapterId) {
                if (eventType === 'image') {
                    setIsIllustrating(false);
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'story', 'images', activeStoryId] });
                    toast.success('Illustration complete');
                } else {
                    // Capture the final streamed content from the ref (always current)
                    // before clearing streaming state, so the base is correct.
                    const finalStreamedText = streamingRef.current;
                    streamingRef.current = '';

                    // Turn off streaming FIRST so the chapter-load effect guard
                    // (isStreamingRef) allows the incoming refetch to update state.
                    setIsStreaming(false);

                    // Update base to the complete streamed content so any subsequent
                    // continuation appends from the right position.
                    setEditorContent(prev => {
                        const newBase = finalStreamedText
                            ? (streamingBaseRef.current
                                ? streamingBaseRef.current + '\n\n' + finalStreamedText
                                : finalStreamedText)
                            : prev;
                        streamingBaseRef.current = newBase;
                        return newBase;
                    });

                    // Invalidate chapter data from server — the chapter-load effect
                    // will only overwrite editor content if the chapter ID changes,
                    // so this is safe.
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] }).then(() => {
                        // Sync the editor with the persisted continuation once the
                        // refetch lands — unless the user has typed since.
                        if (isDirtyRef.current) return;
                        const data = queryClient.getQueryData(['world_vault', 'stories', activeStoryId, 'chapters']);
                        const freshChapter = Array.isArray(data) ? data.find(ch => ch.id === activeChapterId) : null;
                        if (freshChapter?.content && freshChapter.content !== (streamingBaseRef.current || '')) {
                            setEditorContent(freshChapter.content);
                            streamingBaseRef.current = freshChapter.content;
                        }
                    });
                    if (job.id) {
                        clearStreamingJob(queryClient, job.id);
                    }
                }
            }
        });

        const unsubFailed = subscribe(EventTypes.JOB_FAILED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const storyId = meta.story_id;
            const chapterId = meta.chapter_id;

            if (storyId === activeStoryId && chapterId === activeChapterId) {
                setIsStreaming(false);
                setIsIllustrating(false);
                streamingRef.current = '';
                toast.error('Job failed: ' + (job.error || 'Unknown error'));
                if (job.id) {
                    clearStreamingJob(queryClient, job.id);
                }
            }
        });

        // JOB_CANCELLED unhandled before: isStreaming stayed true forever,
        // permanently disabling Save/Continue. Mirror the failed-path cleanup.
        const unsubCancelled = subscribe(EventTypes.JOB_CANCELLED, (event) => {
            const job = getJob(event);
            const meta = job.metadata_ ?? job.metadata ?? {};
            const storyId = meta.story_id;
            const chapterId = meta.chapter_id;

            if (storyId === activeStoryId && chapterId === activeChapterId) {
                setIsStreaming(false);
                setIsIllustrating(false);
                streamingRef.current = '';
                if (job.id) {
                    clearStreamingJob(queryClient, job.id);
                }
            }
        });

        return () => {
            unsubProgress();
            unsubCompleted();
            unsubFailed();
            unsubCancelled();
        };
    // NOTE: editorContent intentionally excluded — we use refs for live values
    // inside the WebSocket handlers to avoid stale closure overwrites.
    }, [subscribe, activeStoryId, activeChapterId, queryClient]);

    // Safety valve for the streaming lock: arm whenever streaming starts,
    // clear whenever it stops (terminal WS event or manual reset).
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

    // Auto-resize textarea — debounced to avoid layout thrashing on mobile
    useEffect(() => {
        const timer = setTimeout(() => {
            if (textareaRef.current) {
                textareaRef.current.style.height = 'auto';
                textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
            }
        }, 150);
        return () => clearTimeout(timer);
    }, [editorContent]);

    // Auto-save chapter content — debounced (2s after last keystroke) so we
    // don't hammer the API. Skipped while streaming (the server pushes the
    // updated content via WebSocket and refetches).
    const autoSaveTimerRef = useRef(null);
    useEffect(() => {
        if (!activeChapterId || isStreaming) return;
        if (editorContent === (activeChapter?.content || '') && !isDirtyRef.current) return;
        if (activeChapterId !== loadedChapterIdRef.current) return;

        const currentContent = editorContent;
        autoSaveTimerRef.current = setTimeout(() => {
            if (
                activeChapterId &&
                !isStreamingRef.current &&
                currentContent === editorContent
            ) {
                updateChapter.mutate({
                    storyId: activeStoryId,
                    chapterId: activeChapterId,
                    content: currentContent,
                });
                isDirtyRef.current = false;
            }
        }, 2000);
        return () => clearTimeout(autoSaveTimerRef.current);
    }, [editorContent, activeChapterId, isStreaming, activeStoryId, updateChapter, activeChapter?.content]);

    const handleContinue = useCallback(async () => {
        if (!activeStoryId || !activeChapterId || isStreaming) return;
        setIsStreaming(true);
        streamingBaseRef.current = editorContent;
        try {
            await continueChapter.mutateAsync({ storyId: activeStoryId, chapterId: activeChapterId });
            toast('AI is continuing the story...', { icon: '📖' });
        } catch {
            toast.error('Failed to start story continuation');
            setIsStreaming(false);
        }
    }, [activeStoryId, activeChapterId, isStreaming, continueChapter, editorContent]);

    const handleAutoGenerateTitle = async () => {
        if (!activeStoryId || !activeChapterId) return;
        titlePollCancelledRef.current = false;
        setIsGeneratingTitle(true);
        toast('Generating title...', { icon: '🤖' });
        try {
            const { text, cancelled } = await runLLMJob({
                workflow: {
                    model: defaultLlmConfig?.model_id || null,
                    messages: [
                        { role: "system", content: "You are an expert author. Analyze the following story chapter and generate a short, catchy title (max 5 words). Output ONLY the title, no quotes or prefix." },
                        { role: "user", content: editorContent.substring(0, 2000) || "A new beginning." }
                    ]
                },
                isCancelled: () => titlePollCancelledRef.current,
            });
            if (cancelled) return;
            if (!text) {
                toast.error('Title generation failed');
                return;
            }
            const newTitle = text.replace(/["']/g, '');
            await api.put(`/api/v2/stories/${activeStoryId}/chapters/${activeChapterId}`, { title: newTitle });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
            toast.success('Title generated!');
        } catch {
            toast.error('Failed to generate title');
        } finally {
            setIsGeneratingTitle(false);
        }
    };

    const handleAddBeat = useCallback(async () => {
        if (!beatInput.trim() || !activeStoryId || !activeChapterId) return;
        try {
            const newBeat = beatInput.trim();
            const newContent = editorContent ? editorContent + '\n\n' + newBeat : newBeat;
            setEditorContent(newContent);
            streamingBaseRef.current = newContent;

            await addStoryBeat.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                content: newBeat
            });
            setBeatInput('');
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
            toast.success('Beat added');
        } catch {
            toast.error('Failed to add beat');
        }
    }, [beatInput, activeStoryId, activeChapterId, addStoryBeat, queryClient, editorContent]);

    const handleBranchFromBeat = useCallback(async (beatId) => {
        if (!activeStoryId || !activeChapterId || isStreaming || branchChapter.isPending) return;
        const ok = await confirm({
            title: 'Branch Story',
            message: 'Fork the story from this beat into a new chapter? The original chapter is untouched.',
            confirmText: 'Branch',
        });
        if (!ok) return;
        setBranchingBeatId(beatId);
        try {
            const branch = await branchChapter.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                fromBeatId: beatId,
            });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
            navigate(`/story/${activeStoryId}/chapter/${branch.id}`);
            toast.success('Branch created');
        } catch {
            toast.error('Failed to create branch');
        } finally {
            setBranchingBeatId(null);
        }
    }, [activeStoryId, activeChapterId, isStreaming, branchChapter, confirm, queryClient, navigate]);

    const handleCreateStory = async (data) => {
        return createStory.mutateAsync(data);
    };

    const handleCreateChapter = async (data) => {
        return createChapter.mutateAsync({ storyId: activeStoryId, data });
    };

    const handleDeleteStory = async (story) => {
        const ok = await confirm({
            title: 'Delete Story',
            message: `Are you sure you want to delete "${story.title}"? All chapters will be lost.`,
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteStory.mutateAsync(story.id);
            if (activeStoryId === story.id) {
                const remaining = stories.filter(s => s.id !== story.id);
                if (remaining.length > 0) {
                    navigate(`/story/${remaining[0].id}`);
                } else {
                    navigate('/story');
                }
            }
            toast.success('Story deleted');
        } catch {
            toast.error('Failed to delete story');
        }
    };

    const handleDeleteChapter = async (chapterId) => {
        if (!activeStoryId) return;
        try {
            await deleteChapter.mutateAsync({ storyId: activeStoryId, chapterId });
            if (activeChapterId === chapterId) {
                const remaining = chapters.filter(ch => ch.id !== chapterId);
                if (remaining.length > 0) {
                    navigate(`/story/${activeStoryId}/chapter/${remaining[0].id}`);
                } else {
                    navigate(`/story/${activeStoryId}`);
                }
            }
            toast.success('Chapter deleted');
        } catch {
            toast.error('Failed to delete chapter');
        }
    };

    const handleSaveChapter = useCallback(async () => {
        if (!activeStoryId || !activeChapterId || isStreaming) return;
        try {
            await updateChapter.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                content: editorContent
            });
            isDirtyRef.current = false;
            toast.success('Chapter saved');
        } catch {
            toast.error('Failed to save chapter');
        }
    }, [activeStoryId, activeChapterId, editorContent, isStreaming, updateChapter]);

    const handleIllustrate = useCallback(async () => {
        if (!activeStoryId || !activeChapterId || isIllustrating) return;
        setShowIllustrateModal(true);
    }, [activeStoryId, activeChapterId, isIllustrating]);

    const handleConfirmIllustrate = useCallback(async () => {
        if (!activeStoryId || !activeChapterId) return;
        setIsIllustrating(true);
        setShowIllustrateModal(false);
        try {
            await illustrateChapter.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                image_prompt: illustratePrompt.trim()
            });
            setIllustratePrompt('');
            toast('Generating illustration...', { icon: '🎨' });
        } catch {
            toast.error('Failed to start illustration');
            setIsIllustrating(false);
        }
    }, [activeStoryId, activeChapterId, illustratePrompt, illustrateChapter]);

    const handleStoryTitleUpdate = async (e) => {
        const newTitle = e.target.value;
        if (!activeStoryId || !newTitle.trim()) return;
        try {
            await api.put(`/api/v2/stories/${activeStoryId}`, { title: newTitle });
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories'] });
        } catch { /* silent */ }
    };

    const handleSaveImageToCollection = useCallback(async (collectionId, path) => {
        if (!collectionId || !path) return;
        try {
            await addImagesToCollection(collectionId, [path]);
            queryClient.invalidateQueries({ queryKey: ['collections'] });
            toast.success('Image saved to collection');
        } catch {
            toast.error('Failed to save image');
        }
    }, [queryClient]);

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex h-full bg-[#0B0E14]"
        >
            <div className={clsx(
                "lg:static inset-y-0 left-0 z-50 transform lg:transform-none transition-transform duration-300 ease-in-out h-full flex flex-col shrink-0 lg:w-64",
                mobileTab === 'stories' ? "absolute inset-0 w-full z-40 bg-[#0B0E14] flex" : "hidden lg:flex"
            )}>
                <StorySidebar
                    stories={stories}
                    activeStoryId={activeStoryId}
                    onSelectStory={(id) => { navigate(`/story/${id}`); setMobileTab('write'); }}
                    onCreateStory={handleCreateStory}
                    onDeleteStory={handleDeleteStory}
                    isLoading={storiesLoading}
                />
                {activeStoryId && (
                    <ChapterSidebar
                        chapters={chapters}
                        activeChapterId={activeChapterId}
                        onSelectChapter={(id) => { navigate(`/story/${activeStoryId}/chapter/${id}`); setMobileTab('write'); }}
                        onCreateChapter={handleCreateChapter}
                        onDeleteChapter={handleDeleteChapter}
                        isLoading={chaptersLoading}
                    />
                )}
            </div>

            <div className="flex-1 flex flex-col min-w-0 relative">
                {/* Mobile top tab strip removed — replaced by the shared
                    <BottomTabBar> fixed to the bottom of the viewport. */}
                {!activeStoryId ? (
                    <div className="flex-1 flex items-center justify-center">
                        <EmptyState
                            title="No Story Selected"
                            description="Select a story from the sidebar or create a new one to start writing."
                            primaryLabel="Create Story"
                            primaryAction={() => {
                                const title = prompt('Story title:');
                                if (title) handleCreateStory({ title });
                            }}
                        />
                    </div>
                ) : (
                    <>
                        <div className="flex-1 flex min-h-0 relative">
                            <div className={clsx(
                                "flex-1 flex flex-col min-w-0",
                                mobileTab === 'write' ? "flex" : "hidden lg:flex"
                            )}>
                                <div className="h-16 border-b border-white/5 flex items-center justify-between px-2 sm:px-6 bg-gray-900/60 backdrop-blur-md z-10 shrink-0 gap-2">
                                    <div className="flex items-center gap-1 sm:gap-3 min-w-0 flex-1">
                                        <div className="md:hidden p-1.5 sm:p-2 text-gray-500">
                                            <BookOpen size={20} />
                                        </div>
                                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-white/10 hidden sm:flex items-center justify-center shrink-0">
                                            <BookOpen className="text-indigo-400" size={20} />
                                        </div>
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-center gap-2 min-w-0">
                                                <input
                                                    type="text"
                                                    defaultValue={activeStory?.title || ''}
                                                    onBlur={handleStoryTitleUpdate}
                                                    className="bg-transparent font-semibold text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 rounded px-1 transition-all w-full truncate text-sm sm:text-base"
                                                />
                                            </div>
                                            <div className="flex items-center gap-1 sm:gap-2 px-1 min-w-0">
                                                <div className="flex flex-col min-w-0">
                                                    <p className="font-bold text-sm sm:text-base text-gray-200 truncate flex items-center gap-2">
                                                        {activeChapter ? `${activeChapter.title || `Chapter ${activeChapter.chapter_number}`}` : 'Select a chapter'}
                                                        {activeStory?.genre && <span className="hidden sm:inline font-normal text-xs text-gray-500">· {activeStory.genre}</span>}
                                                    </p>
                                                </div>
                                                {activeChapter && (
                                                    <button 
                                                        onClick={handleAutoGenerateTitle} 
                                                        disabled={isGeneratingTitle}
                                                        className="text-[10px] bg-indigo-500/10 text-indigo-400 px-1.5 py-0.5 rounded hover:bg-indigo-500/20 transition-colors flex items-center gap-1 disabled:opacity-50 shrink-0"
                                                        title="Auto-generate chapter title using AI"
                                                    >
                                                        {isGeneratingTitle ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                                                        <span className="hidden sm:inline">Auto Title</span>
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                    
                                    <div className="flex items-center gap-1 sm:gap-2 shrink-0">
                                        {activeChapterId && (
                                            <button
                                                onClick={handleSaveChapter}
                                                disabled={isStreaming || updateChapter.isPending}
                                                className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-green-500/20 text-green-300 rounded-lg hover:bg-green-500/30 transition-colors disabled:opacity-30"
                                                title="Save chapter content"
                                            >
                                                {updateChapter.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={14} />}
                                                Save
                                            </button>
                                        )}
                                                <button
                                                    onClick={() => setIsPreviewMode(!isPreviewMode)}
                                                    className={clsx(
                                                        "p-1.5 sm:p-2 rounded-lg transition-colors border",
                                                        isPreviewMode ? "bg-purple-500/20 text-purple-400 border-purple-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                                                    )}
                                                    title={isPreviewMode ? "Edit Mode" : "Preview Mode"}
                                                >
                                                    {isPreviewMode ? <Edit3 size={16} /> : <Book size={16} />}
                                                </button>
                                        <button
                                            onClick={() => { setIsPanelOpen(!isPanelOpen); setMobileTab('context'); }}
                                            className={clsx(
                                                "p-2 rounded-lg transition-colors border flex lg:hidden",
                                                mobileTab === 'context' ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                                            )}
                                        >
                                            <Layers size={20} />
                                        </button>
                                        <button
                                            onClick={() => setIsPanelOpen(!isPanelOpen)}
                                            className={clsx(
                                                "p-2 rounded-lg transition-colors border hidden lg:flex",
                                                isPanelOpen ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                                            )}
                                        >
                                            <ImageIcon size={20} />
                                        </button>
                                    </div>
                                </div>

                                <div className="flex-1 overflow-y-auto custom-scrollbar flex justify-center p-6 lg:p-12">
                                    {!activeChapterId ? (
                                        <div className="flex items-center justify-center text-gray-500">
                                            <p className="text-sm">Select or create a chapter to start writing</p>
                                        </div>
                                    ) : (
                                        <div className="w-full max-w-3xl relative h-full min-h-[300px]">
                                            {isPreviewMode ? (
                                                <div className="w-full text-gray-300 text-lg md:text-xl leading-relaxed font-serif prose prose-invert max-w-none">
                                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                        {editorContent || '*No content yet.*'}
                                                    </ReactMarkdown>
                                                </div>
                                            ) : (
                                                <textarea
                                                    ref={textareaRef}
                                                    value={editorContent}
                                                    onChange={(e) => { isDirtyRef.current = true; setEditorContent(e.target.value); }}
                                                    className="story-editor-input w-full h-full bg-transparent text-gray-300 text-lg md:text-xl leading-relaxed font-serif focus:outline-none resize-none min-h-[300px]"
                                                    placeholder="Begin your story here (Markdown supported)..."
                                                    disabled={isStreaming}
                                                />
                                            )}
                                            
                                            {isStreaming && (
                                                <div className="flex items-center gap-2 text-indigo-400 font-serif mt-4 story-stream-pulse">
                                                    <Sparkles size={16} />
                                                    <span>The AI is weaving the next thread...</span>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {activeChapterId && (
                                    <div className="px-2 sm:px-4 lg:px-6 pb-16 md:pb-4 pt-2 border-t border-white/5 bg-gray-900/40 shrink-0">
                                        {showBeatsPanel && (
                                            <div className="max-w-3xl mx-auto mb-3 max-h-56 overflow-y-auto custom-scrollbar rounded-xl border border-white/5 bg-gray-950/60 p-3 space-y-1.5">
                                                <div className="flex items-center justify-between mb-1.5">
                                                    <h4 className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-1.5">
                                                        <GitBranch size={11} /> Story Beats
                                                    </h4>
                                                    <button
                                                        onClick={() => setShowBeatsPanel(false)}
                                                        className="p-1 text-gray-500 hover:text-white hover:bg-white/10 rounded transition-colors"
                                                        title="Close beats panel"
                                                    >
                                                        <X size={12} />
                                                    </button>
                                                </div>
                                                {(activeChapter?.beats || []).length === 0 ? (
                                                    <p className="text-xs text-gray-500 text-center py-2">No beats recorded yet. Use the beat input below or press Continue.</p>
                                                ) : (
                                                    (activeChapter?.beats || []).map((beat, idx) => {
                                                        const beatId = beat?.id || null;
                                                        const isUser = beat?.role === 'user';
                                                        const snippet = (beat?.content || '').length > 140
                                                            ? (beat?.content || '').slice(0, 140) + '…'
                                                            : (beat?.content || '');
                                                        return (
                                                            <div key={beatId || idx} className="group flex items-start gap-2 rounded-lg bg-white/[0.03] border border-white/5 px-2.5 py-1.5">
                                                                <span className={clsx(
                                                                    "mt-0.5 shrink-0 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded",
                                                                    isUser ? "bg-blue-500/15 text-blue-300" : "bg-purple-500/15 text-purple-300"
                                                                )}>
                                                                    {isUser ? 'user' : (beat?.role || 'narrator')}
                                                                </span>
                                                                <p className="flex-1 text-xs text-gray-400 leading-relaxed min-w-0">{snippet || <span className="italic text-gray-600">(empty)</span>}</p>
                                                                <button
                                                                    onClick={() => handleBranchFromBeat(beatId)}
                                                                    disabled={!beatId || isStreaming || branchChapter.isPending || branchingBeatId === beatId}
                                                                    className="shrink-0 opacity-60 group-hover:opacity-100 disabled:opacity-20 flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 hover:bg-amber-500/20 transition-colors"
                                                                    title="Branch the story from this beat into a new chapter"
                                                                >
                                                                    {branchingBeatId === beatId ? <Loader2 size={10} className="animate-spin" /> : <GitBranch size={10} />}
                                                                    Branch
                                                                </button>
                                                            </div>
                                                        );
                                                    })
                                                )}
                                            </div>
                                        )}
                                        <div className="max-w-3xl mx-auto flex flex-col sm:flex-row gap-2 sm:gap-3">
                                            <div className="grid grid-cols-2 sm:flex gap-2 shrink-0">
                                                <button
                                                    onClick={() => setShowBeatsPanel(!showBeatsPanel)}
                                                    className={clsx(
                                                        "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm",
                                                        showBeatsPanel
                                                            ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                                            : "bg-gray-800 text-gray-300 hover:bg-gray-700"
                                                    )}
                                                    title="Show story beats (fork points)"
                                                >
                                                    <GitBranch size={14} />
                                                    <span className="hidden sm:inline">Beats</span>
                                                    <span className="text-[10px] text-gray-500">({(activeChapter?.beats || []).length})</span>
                                                </button>
                                                <button
                                                    onClick={handleContinue}
                                                    disabled={isStreaming || continueChapter.isPending}
                                                    className={clsx(
                                                        "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm",
                                                        isStreaming || continueChapter.isPending
                                                            ? "bg-indigo-500/50 text-white/50 cursor-not-allowed"
                                                            : "bg-indigo-600 text-white hover:bg-indigo-500"
                                                    )}
                                                >
                                                    {isStreaming || continueChapter.isPending ? (
                                                        <><Loader2 size={14} className="animate-spin" /> Gen...</>
                                                    ) : (
                                                        <><Play size={14} fill="currentColor" /> Continue</>
                                                    )}
                                                </button>
                                                <button
                                                    onClick={handleIllustrate}
                                                    disabled={isIllustrating}
                                                    className={clsx(
                                                        "flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all text-sm",
                                                        isIllustrating
                                                            ? "bg-amber-500/50 text-white/50 cursor-not-allowed"
                                                            : "bg-amber-600 text-white hover:bg-amber-500"
                                                    )}
                                                >
                                                    {isIllustrating ? (
                                                        <><Loader2 size={14} className="animate-spin" /> Illus...</>
                                                    ) : (
                                                        <><ImageIcon size={14} /> Illustrate</>
                                                    )}
                                                </button>
                                            </div>

                                            <div className="flex-1 flex gap-2 w-full">
                                                <input
                                                    type="text"
                                                    value={beatInput}
                                                    onChange={(e) => setBeatInput(e.target.value)}
                                                    onKeyDown={(e) => e.key === 'Enter' && handleAddBeat()}
                                                    placeholder="Add a story beat..."
                                                    className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 sm:px-4 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500/50 min-w-0"
                                                />
                                                <button
                                                    onClick={handleAddBeat}
                                                    disabled={!beatInput.trim()}
                                                    className="px-3 sm:px-4 py-2 bg-gray-800 text-gray-300 rounded-lg text-sm font-medium hover:bg-gray-700 disabled:opacity-50 transition-colors shrink-0"
                                                >
                                                    Add
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    </>
                )}
            </div>

            <AnimatePresence initial={false}>
                {(isPanelOpen || mobileTab === 'context') && activeStoryId && (
                    <motion.div
                        initial={{ x: 360, opacity: 0 }}
                        animate={{ x: 0, opacity: 1 }}
                        exit={{ x: 360, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className={clsx(
                            "flex flex-col border-l border-white/5 bg-gray-900/95 overflow-hidden shrink-0 relative",
                            "absolute lg:static inset-y-0 right-0 z-40 h-full max-w-full w-full lg:w-[360px] lg:bg-gray-900/40",
                            mobileTab === 'context' ? "flex" : "hidden lg:flex"
                        )}
                    >
                        <div className="lg:hidden absolute top-3 right-4 z-50">
                            <button onClick={() => { setMobileTab('write'); setIsPanelOpen(false); }} className="p-2 bg-gray-800 rounded-full text-white">
                                <X size={16} />
                            </button>
                        </div>
                        <div className="h-16 border-b border-white/5 flex items-center px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                            <h3 className="font-semibold text-gray-200 flex items-center gap-2">
                                <ImageIcon size={16} className="text-indigo-400" />
                                Story Context
                            </h3>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                                    <Layers size={14} /> Characters
                                </h4>
                                {characters.length === 0 ? (
                                    <p className="text-sm text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">No characters</p>
                                ) : (
                                    <div className="space-y-2">
                                        {characters.map(char => {
                                            const isActive = (activeStory?.character_ids || []).includes(char.id);
                                            return (
                                                <button
                                                    key={char.id}
                                                    onClick={() => {
                                                        const current = activeStory?.character_ids || [];
                                                        const newIds = isActive ? current.filter(id => id !== char.id) : [...current, char.id];
                                                        updateStory.mutate({ id: activeStoryId, character_ids: newIds });
                                                    }}
                                                    className={clsx(
                                                        "w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors",
                                                        isActive ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                                    )}
                                                >
                                                    {isActive ? <Check size={14} className="text-indigo-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                                    <div className="min-w-0">
                                                        <p className="truncate font-medium">{char.name}</p>
                                                    </div>
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>

                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                                    <Layers size={14} /> Lorebooks
                                </h4>
                                {lorebooks.length === 0 ? (
                                    <p className="text-sm text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">No lorebooks</p>
                                ) : (
                                    <div className="space-y-2">
                                        {lorebooks.map(lb => {
                                            const isActive = (activeStory?.lorebook_ids || []).includes(lb.id);
                                            return (
                                                <button
                                                    key={lb.id}
                                                    onClick={() => {
                                                        const current = activeStory?.lorebook_ids || [];
                                                        const newIds = isActive ? current.filter(id => id !== lb.id) : [...current, lb.id];
                                                        updateStory.mutate({ id: activeStoryId, lorebook_ids: newIds });
                                                    }}
                                                    className={clsx(
                                                        "w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors",
                                                        isActive ? "bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border border-transparent"
                                                    )}
                                                >
                                                    {isActive ? <Check size={14} className="text-indigo-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                                    <div className="min-w-0">
                                                        <p className="truncate font-medium">{lb.name}</p>
                                                        {lb.description && <p className="text-[10px] text-gray-500 truncate">{lb.description}</p>}
                                                    </div>
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>

                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <div className="flex items-center justify-between mb-3">
                                    <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                                        <ImageIcon size={14} /> Chapter Images
                                    </h4>
                                    <button
                                        onClick={() => setShowGallery(true)}
                                        className="text-[10px] text-indigo-400 hover:text-indigo-300 transition-colors"
                                    >
                                        View all ({storyImages.length})
                                    </button>
                                </div>
                                {activeChapter?.image_paths?.length > 0 ? (
                                    <div className="space-y-2">
                                        {activeChapter.image_paths.map((path, idx) => (
                                            <div key={idx} className="rounded-lg overflow-hidden border border-white/10">
                                                <img src={assetUrl(path)} alt={`Scene ${idx + 1}`} loading="lazy" decoding="async" className="w-full h-auto" />
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="h-32 border border-dashed border-gray-700 rounded-xl flex flex-col items-center justify-center text-gray-500 gap-2">
                                        <ImageIcon size={24} className="opacity-50" />
                                        <p className="text-xs">No illustrations yet</p>
                                    </div>
                                )}
                            </div>
                            <div className="bg-gray-800/50 p-4 rounded-xl border border-gray-700/50 space-y-4">
                                <div className="flex items-center gap-2 mb-2">
                                    <Settings size={16} className="text-gray-400" />
                                    <h3 className="font-semibold text-gray-200">AI Model Settings</h3>
                                </div>
                                <div>
                                    <label className="text-xs font-semibold text-gray-400 uppercase tracking-wider block mb-2">Text Model</label>
                                    <select
                                        className="w-full bg-gray-900 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-indigo-500/50"
                                        value={activeStory?.llm_model || 'default'}
                                        onChange={(e) => {
                                            if (activeStoryId) {
                                                updateStory.mutate({ id: activeStoryId, llm_model: e.target.value === 'default' ? null : e.target.value });
                                            }
                                        }}
                                    >
                                        <option value="default">Provider Default ({defaultLlmConfig?.model_id || 'default'})</option>
                                        {llmModels.map(m => (
                                            <option key={m.id} value={m.id}>{m.name || m.id}</option>
                                        ))}
                                    </select>
                                    <p className="text-[10px] text-gray-500 mt-1">Per-story model override; used for continuations and titles.</p>
                                </div>
                            </div>
                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <h4 className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                                    <Book size={14} /> Story Info
                                </h4>
                                <div className="space-y-3 text-xs text-gray-400">
                                    <p>Chapters: {chapters?.length || 0}</p>
                                    <p>Status: {activeStory?.is_archived ? 'Archived' : 'Active'}</p>
                                    {activeStory?.created_at && (
                                        <p className="flex items-center gap-1">
                                            <Calendar size={10} className="text-gray-600" />
                                            Created: {new Date(activeStory.created_at).toLocaleDateString()}
                                        </p>
                                    )}
                                </div>
                            </div>

                            {/* Genre */}
                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                                    <Tag size={12} className="text-purple-400" /> Genre
                                </label>
                                <input
                                    type="text"
                                    value={activeStory?.genre || ''}
                                    onChange={(e) => {
                                        if (activeStoryId) {
                                            updateStory.mutate({ id: activeStoryId, genre: e.target.value.trim() || null });
                                        }
                                    }}
                                    placeholder="e.g. Fantasy, Cyberpunk, Horror"
                                    className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50 transition-colors"
                                />
                                <p className="text-[10px] text-gray-500 mt-1">Steer story continuation tone/style.</p>
                            </div>

                            {/* Description */}
                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
                                    Description
                                </label>
                                <textarea
                                    value={activeStory?.description || ''}
                                    onChange={(e) => {
                                        if (activeStoryId) {
                                            updateStory.mutate({ id: activeStoryId, description: e.target.value.trim() || null });
                                        }
                                    }}
                                    placeholder="A brief description of this story world..."
                                    rows={3}
                                    className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50 resize-none"
                                />
                            </div>

                            {/* Memory / Author's Note */}
                            <div className="glass-panel p-4 rounded-xl border border-white/5">
                                <label className="block text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                                    <PenTool size={12} className="text-amber-400" /> Memory (Author's Note)
                                </label>
                                <textarea
                                    value={activeStory?.memory || ''}
                                    onChange={(e) => {
                                        if (activeStoryId) {
                                            updateStory.mutate({ id: activeStoryId, memory: e.target.value.trim() || null });
                                        }
                                    }}
                                    placeholder="Persistent facts the AI should always remember (e.g. the protagonist is cursed to turn to stone at midnight)..."
                                    rows={3}
                                    className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500/50 resize-none"
                                />
                                <p className="text-[10px] text-gray-500 mt-1">Injected into every story continuation prompt.</p>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Illustrate Prompt Modal */}
            <AnimatePresence>
                {showIllustrateModal && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                        onClick={() => setShowIllustrateModal(false)}
                    >
                        <motion.div
                            initial={{ scale: 0.95, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.95, opacity: 0 }}
                            className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl"
                            onClick={e => e.stopPropagation()}
                        >
                            <h3 className="text-lg font-semibold text-gray-100 flex items-center gap-2 mb-4">
                                <ImageIcon size={18} className="text-amber-400" />
                                Generate Illustration
                            </h3>
                            <p className="text-sm text-gray-400 mb-4">
                                Optionally describe what you want to see, or leave blank for the AI to choose based on the chapter content.
                            </p>
                            <textarea
                                value={illustratePrompt}
                                onChange={e => setIllustratePrompt(e.target.value)}
                                placeholder="e.g. A moonlit forest clearing with a mysterious figure... (optional)"
                                className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500/50 resize-none h-24 mb-4"
                                autoFocus
                            />
                            <div className="flex gap-2 justify-end">
                                <button
                                    onClick={() => { setShowIllustrateModal(false); setIllustratePrompt(''); }}
                                    className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleConfirmIllustrate}
                                    className="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg hover:bg-amber-500 transition-colors flex items-center gap-2"
                                >
                                    <ImageIcon size={14} />
                                    Generate
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Story Gallery Modal */}
            <AnimatePresence>
                {showGallery && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
                        onClick={() => setShowGallery(false)}
                    >
                        <motion.div
                            initial={{ scale: 0.95, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.95, opacity: 0 }}
                            className="bg-gray-900 border border-white/10 rounded-3xl shadow-2xl w-full max-w-5xl flex flex-col h-[85vh] overflow-hidden"
                            onClick={e => e.stopPropagation()}
                        >
                            <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                                <h3 className="font-bold text-gray-100 flex items-center gap-2">
                                    <ImageIcon size={16} className="text-indigo-400" />
                                    {activeStory?.title || 'Story'} Gallery
                                </h3>
                                <button onClick={() => setShowGallery(false)} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                                    <X size={18} />
                                </button>
                            </div>
                            <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                                <SceneGallery
                                    title={`${activeStory?.title || 'Story'} gallery`}
                                    images={storyImages.map(img => img.path)}
                                    lightboxAction={(path) => (
                                        <select
                                            value=""
                                            onChange={(e) => {
                                                if (e.target.value) {
                                                    handleSaveImageToCollection(e.target.value, path);
                                                    e.target.value = '';
                                                }
                                            }}
                                            className="bg-gray-800 border border-white/10 rounded-lg text-xs text-gray-200 px-2 py-1.5 cursor-pointer hover:border-indigo-500/40 transition-colors"
                                            title="Save to collection"
                                        >
                                            <option value="">Save to…</option>
                                            {collectionsList.map(c => (
                                                <option key={c.id} value={c.id}>{c.name}</option>
                                            ))}
                                        </select>
                                    )}
                                />
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Shared mobile bottom tab bar for the StorySandbox workspaces. */}
            <BottomTabBar
                tabs={[
                    { id: 'stories', label: 'Stories', icon: BookOpen },
                    { id: 'write', label: 'Write', icon: Edit3 },
                    { id: 'context', label: 'Context', icon: Layers },
                ]}
                value={mobileTab}
                onChange={setMobileTab}
                label="Story sandbox navigation"
            />

            {/* Single-layer CSS pulse for the streaming indicator (replaces
                Tailwind's per-frame animate-pulse, §1.1). One animated layer,
                not N nested pulsing divs. */}
            <style>{`
@keyframes tnh-stream-pulse { 0%,100% { opacity: .45; } 50% { opacity: 1; } }
.story-stream-pulse { animation: tnh-stream-pulse 1.5s ease-in-out infinite; }
`}</style>
        </motion.div>
    );
}
