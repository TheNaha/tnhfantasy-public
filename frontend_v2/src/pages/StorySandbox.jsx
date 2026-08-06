import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, Sparkles, Image as ImageIcon, Save, Undo2, Play, Settings, Type, Plus, Loader2, Trash2, ChevronRight, Edit3, Book, Layers, Check, Columns, X } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useStories, useStory, useStoryChapters, useCreateStory, useCreateChapter, useContinueChapter, useAddStoryBeat, useLorebooks, useDeleteStory, useDeleteChapter, useUpdateChapter, useUpdateStory, useIllustrateChapter, useLLMAvailableModels, useLLMDefaultProvider } from '../hooks/useWorldVault';
import { api } from '../api';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useQueryClient } from '@tanstack/react-query';
import EmptyState from '../components/EmptyState';
import ConfirmationModal from '../components/ConfirmationModal';
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
        <div className="w-64 border-r border-white/5 bg-gray-900/60 flex flex-col shrink-0">
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
        <div className="w-56 border-r border-white/5 bg-gray-900/40 flex flex-col shrink-0">
            <div className="h-12 flex items-center justify-between px-3 border-b border-white/5 shrink-0">
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Chapters</h4>
                <button onClick={handleCreate} disabled={creating} className="p-1 text-gray-400 hover:text-white hover:bg-white/10 rounded transition-colors disabled:opacity-30" title="New chapter">
                    <Plus size={14} />
                </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
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
    const [isPanelOpen, setIsPanelOpen] = useState(true);
    const [editorContent, setEditorContent] = useState('');
    const [beatInput, setBeatInput] = useState('');
    const textareaRef = useRef(null);
    const streamingRef = useRef('');
    const streamingBaseRef = useRef('');
    const loadedChapterIdRef = useRef(null);

    const queryClient = useQueryClient();
    const activeStoryId = useWorldVaultStore(state => state.activeStoryId);
    const setActiveStory = useWorldVaultStore(state => state.setActiveStory);
    const selectedLorebooks = useWorldVaultStore(state => state.contextBuilder.selectedLorebooks);
    const toggleLorebook = useWorldVaultStore(state => state.toggleLorebook);

    const { data: stories = [], isLoading: storiesLoading } = useStories();
    const { data: activeStory } = useStory(activeStoryId);
    const { data: chapters = [], isLoading: chaptersLoading } = useStoryChapters(activeStoryId);
    const { data: lorebooks = [] } = useLorebooks();

    const createStory = useCreateStory();
    const createChapter = useCreateChapter();
    const continueChapter = useContinueChapter();
    const addStoryBeat = useAddStoryBeat();
    const deleteStory = useDeleteStory();
    const deleteChapter = useDeleteChapter();
    const updateChapter = useUpdateChapter();
    const illustrateChapter = useIllustrateChapter();

    const [activeChapterId, setActiveChapterId] = useState(null);
    const [isStreaming, setIsStreaming] = useState(false);
    const [deleteConfirm, setDeleteConfirm] = useState(null);
    const [illustratePrompt, setIllustratePrompt] = useState('');
    const [showIllustrateModal, setShowIllustrateModal] = useState(false);
    const [isIllustrating, setIsIllustrating] = useState(false);
    const [isPreviewMode, setIsPreviewMode] = useState(false);
    const [mobileTab, setMobileTab] = useState('write'); // 'stories' | 'chapters' | 'write' | 'context'
    const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);

    const { data: llmModels = [] } = useLLMAvailableModels();
    const { data: defaultLlmConfig } = useLLMDefaultProvider();
    const updateStory = useUpdateStory();

    const { subscribe } = useWebSocket();

    const activeChapter = chapters?.find(ch => ch.id === activeChapterId);

    // Auto-select first story
    useEffect(() => {
        if (stories?.length > 0 && !activeStoryId) {
            setActiveStory(stories[0].id);
        }
    }, [stories, activeStoryId, setActiveStory]);

    // Auto-select first chapter
    useEffect(() => {
        if (chapters?.length > 0 && !activeChapterId) {
            // Wait for next tick to avoid synchronous cascading renders
            setTimeout(() => setActiveChapterId(chapters[0].id), 0);
        }
    }, [chapters, activeChapterId]);

    // Load chapter content into editor
    useEffect(() => {
        if (activeChapter && loadedChapterIdRef.current !== activeChapterId) {
            loadedChapterIdRef.current = activeChapterId;
            // Wait for next tick to avoid synchronous cascading renders
            setTimeout(() => {
                setEditorContent(activeChapter.content || '');
                streamingRef.current = '';
                streamingBaseRef.current = activeChapter.content || '';
            }, 0);
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
                    // Show accumulated text in editor while generating
                    setEditorContent(() => {
                        const baseContent = streamingBaseRef.current || '';
                        // Only append if the streaming text is not already in the content
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
                    toast.success('Illustration complete');
                } else {
                    setIsStreaming(false);
                    streamingRef.current = '';
                    streamingBaseRef.current = editorContent;
                    queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
                    if (job.id) {
                        useWorldVaultStore.getState().clearStreamingJob(job.id);
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
                    useWorldVaultStore.getState().clearStreamingJob(job.id);
                }
            }
        });

        return () => {
            unsubProgress();
            unsubCompleted();
            unsubFailed();
        };
    }, [subscribe, activeStoryId, activeChapterId, queryClient, editorContent]);

    // Auto-resize textarea
    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
        }
    }, [editorContent]);

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
        setIsGeneratingTitle(true);
        toast('Generating title...', { icon: '🤖' });
        try {
            const resJob = await api.post('/api/jobs', {
                task_type: "llm",
                workflow: {
                    model: defaultLlmConfig?.model_id || null,
                    messages: [
                        { role: "system", content: "You are an expert author. Analyze the following story chapter and generate a short, catchy title (max 5 words). Output ONLY the title, no quotes or prefix." },
                        { role: "user", content: editorContent.substring(0, 2000) || "A new beginning." }
                    ]
                }
            });
            toast.success('Title generation started...');
            const pollJob = async (jobId) => {
                for (let i = 0; i < 30; i++) {
                    const jobStatus = await api.get(`/api/jobs/${jobId}`);
                    if (jobStatus.status === 'completed' && jobStatus.outputs?.length > 0) {
                        const newTitle = jobStatus.outputs[0].content.replace(/["']/g, '');
                        await api.put(`/api/v2/stories/${activeStoryId}/chapters/${activeChapterId}`, { title: newTitle });
                        queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
                        toast.success('Title generated!');
                        setIsGeneratingTitle(false);
                        return;
                    }
                    if (jobStatus.status === 'failed') break;
                    await new Promise(r => setTimeout(r, 1000));
                }
                toast.error('Title generation failed');
                setIsGeneratingTitle(false);
            };
            if (resJob.id) {
                pollJob(resJob.id);
            } else {
                setIsGeneratingTitle(false);
            }
        } catch {
            toast.error('Failed to generate title');
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

    const handleCreateStory = async (data) => {
        return createStory.mutateAsync(data);
    };

    const handleCreateChapter = async (data) => {
        return createChapter.mutateAsync({ storyId: activeStoryId, data });
    };

    const handleDeleteStory = async (story) => {
        setDeleteConfirm(story);
    };

    const confirmDeleteStory = async () => {
        if (!deleteConfirm) return;
        try {
            await deleteStory.mutateAsync(deleteConfirm.id);
            if (activeStoryId === deleteConfirm.id) {
                const remaining = stories.filter(s => s.id !== deleteConfirm.id);
                setActiveStory(remaining[0]?.id || null);
                setActiveChapterId(null);
            }
            toast.success('Story deleted');
        } catch {
            toast.error('Failed to delete story');
        }
        setDeleteConfirm(null);
    };

    const handleDeleteChapter = async (chapterId) => {
        if (!activeStoryId) return;
        try {
            await deleteChapter.mutateAsync({ storyId: activeStoryId, chapterId });
            if (activeChapterId === chapterId) {
                const remaining = chapters.filter(ch => ch.id !== chapterId);
                setActiveChapterId(remaining[0]?.id || null);
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

    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="flex h-[calc(var(--vh,1vh)*100-8rem)] lg:h-[calc(var(--vh,1vh)*100-4rem)] -mx-2 sm:-mx-4 lg:-mx-8 -my-3 sm:-my-4 lg:-my-8 bg-[#0B0E14]"
        >
            <div className={clsx(
                "md:static inset-y-0 left-0 z-50 transform md:transform-none transition-transform duration-300 ease-in-out h-full flex flex-col shrink-0",
                mobileTab === 'stories' ? "absolute inset-0 w-full z-40 bg-[#0B0E14] flex" : "hidden md:flex"
            )}>
                <StorySidebar
                    stories={stories}
                    activeStoryId={activeStoryId}
                    onSelectStory={(id) => { setActiveStory(id); setActiveChapterId(null); setMobileTab('write'); }}
                    onCreateStory={handleCreateStory}
                    onDeleteStory={handleDeleteStory}
                    isLoading={storiesLoading}
                />
            </div>

            <div className="flex-1 flex flex-col min-w-0 relative">
                {/* Mobile Top Tab Strip */}
                <div className="flex md:hidden border-b border-white/5 bg-gray-900/60 backdrop-blur-md p-2 gap-2 shrink-0">
                    <button onClick={() => setMobileTab('stories')} className={clsx("flex-1 py-1.5 text-[11px] font-medium rounded-lg transition-colors", mobileTab === 'stories' ? "bg-indigo-500/20 text-indigo-400" : "text-gray-400 hover:text-gray-200")}>Stories</button>
                    <button onClick={() => setMobileTab('chapters')} className={clsx("flex-1 py-1.5 text-[11px] font-medium rounded-lg transition-colors", mobileTab === 'chapters' ? "bg-indigo-500/20 text-indigo-400" : "text-gray-400 hover:text-gray-200")}>Chapters</button>
                    <button onClick={() => setMobileTab('write')} className={clsx("flex-1 py-1.5 text-[11px] font-medium rounded-lg transition-colors", mobileTab === 'write' ? "bg-indigo-500/20 text-indigo-400" : "text-gray-400 hover:text-gray-200")}>Write</button>
                    <button onClick={() => setMobileTab('context')} className={clsx("flex-1 py-1.5 text-[11px] font-medium rounded-lg transition-colors", mobileTab === 'context' ? "bg-indigo-500/20 text-indigo-400" : "text-gray-400 hover:text-gray-200")}>Context</button>
                </div>
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
                                "md:static inset-y-0 left-0 z-30 transform md:transform-none transition-transform duration-300 ease-in-out h-full flex flex-col shrink-0",
                                mobileTab === 'chapters' ? "absolute inset-0 w-full z-40 bg-[#0B0E14] flex" : "hidden md:flex"
                            )}>
                                <ChapterSidebar
                                    chapters={chapters}
                                    activeChapterId={activeChapterId}
                                    onSelectChapter={(id) => { setActiveChapterId(id); setMobileTab('write'); }}
                                    onCreateChapter={handleCreateChapter}
                                    onDeleteChapter={handleDeleteChapter}
                                    isLoading={chaptersLoading}
                                />
                            </div>

                            <div className={clsx(
                                "flex-1 flex flex-col min-w-0",
                                mobileTab === 'write' ? "flex" : "hidden md:flex"
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
                                                        <span className="lg:hidden text-gray-500">▼</span>
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
                                                "p-2 rounded-lg transition-colors border flex md:hidden",
                                                mobileTab === 'context' ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                                            )}
                                        >
                                            <Layers size={20} />
                                        </button>
                                        <button
                                            onClick={() => setIsPanelOpen(!isPanelOpen)}
                                            className={clsx(
                                                "p-2 rounded-lg transition-colors border hidden md:flex",
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
                                                    onChange={(e) => setEditorContent(e.target.value)}
                                                    className="story-editor-input w-full h-full bg-transparent text-gray-300 text-lg md:text-xl leading-relaxed font-serif focus:outline-none resize-none min-h-[300px]"
                                                    placeholder="Begin your story here (Markdown supported)..."
                                                    disabled={isStreaming}
                                                />
                                            )}
                                            
                                            {isStreaming && (
                                                <div className="flex items-center gap-2 text-indigo-400 font-serif mt-4 animate-pulse">
                                                    <Sparkles size={16} />
                                                    <span>The AI is weaving the next thread...</span>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {activeChapterId && (
                                    <div className="px-2 sm:px-4 lg:px-6 pb-16 md:pb-4 pt-2 border-t border-white/5 bg-gray-900/40 shrink-0">
                                        <div className="max-w-3xl mx-auto flex flex-col sm:flex-row gap-2 sm:gap-3">
                                            <div className="grid grid-cols-2 sm:flex gap-2 shrink-0">
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
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: 360, opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className={clsx(
                            "flex flex-col border-l border-white/5 bg-gray-900/95 overflow-hidden shrink-0 relative",
                            "absolute md:static inset-y-0 right-0 z-40 h-full max-w-full w-full md:w-[360px] md:bg-gray-900/40",
                            mobileTab === 'context' ? "flex" : "hidden md:flex"
                        )}
                    >
                        <div className="md:hidden absolute top-3 right-4 z-50">
                            <button onClick={() => setMobileTab('write')} className="p-2 bg-gray-800 rounded-full text-white">
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
                                    <Layers size={14} /> Lorebooks
                                </h4>
                                {lorebooks.length === 0 ? (
                                    <p className="text-sm text-gray-500 text-center py-3 border border-dashed border-gray-700/50 rounded-lg">No lorebooks</p>
                                ) : (
                                    <div className="space-y-2">
                                        {lorebooks.map(lb => {
                                            const isActive = selectedLorebooks.includes(lb.id);
                                            return (
                                                <button
                                                    key={lb.id}
                                                    onClick={() => toggleLorebook(lb.id)}
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
                                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                                    <ImageIcon size={14} /> Chapter Images
                                </h4>
                                {activeChapter?.image_paths?.length > 0 ? (
                                    <div className="space-y-2">
                                        {activeChapter.image_paths.map((path, idx) => (
                                            <div key={idx} className="rounded-lg overflow-hidden border border-white/10">
                                                <img src={`/api/files/${path}`} alt={`Scene ${idx + 1}`} className="w-full h-auto" />
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
                                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Story Info</h4>
                                <div className="space-y-2 text-xs text-gray-500">
                                    <p>Chapters: {chapters?.length || 0}</p>
                                    <p>Genre: {activeStory?.genre || 'Not set'}</p>
                                    <p>Status: {activeStory?.is_archived ? 'Archived' : 'Active'}</p>
                                    {activeStory?.description && <p className="italic mt-2">{activeStory.description}</p>}
                                </div>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>

            <ConfirmationModal
                isOpen={!!deleteConfirm}
                onClose={() => setDeleteConfirm(null)}
                onConfirm={confirmDeleteStory}
                title="Delete Story"
                message={`Are you sure you want to delete "${deleteConfirm?.title}"? All chapters will be lost.`}
                confirmText="Delete"
                isDangerous
            />


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
        </motion.div>
    );
}
