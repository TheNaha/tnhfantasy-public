import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BookOpen, Sparkles, Image as ImageIcon, Save, Undo2, Play, Settings, Type, Plus, Loader2, Trash2, ChevronRight, Edit3, Book, Layers, Check } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useStories, useStory, useStoryChapters, useCreateStory, useCreateChapter, useContinueChapter, useAddStoryBeat, useLorebooks, useDeleteStory, useDeleteChapter, useUpdateChapter } from '../hooks/useWorldVault';
import { api } from '../api';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useQueryClient } from '@tanstack/react-query';
import EmptyState from '../components/EmptyState';
import ConfirmationModal from '../components/ConfirmationModal';

function StorySidebar({ stories, activeStoryId, onSelectStory, onCreateStory, onDeleteStory, isLoading }) {
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
        <div className="w-64 border-r border-white/5 bg-gray-900/60 hidden md:flex flex-col shrink-0">
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
}

function ChapterSidebar({ chapters, activeChapterId, onSelectChapter, onCreateChapter, onDeleteChapter, isLoading }) {
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
        <div className="w-56 border-r border-white/5 bg-gray-900/40 hidden lg:flex flex-col shrink-0">
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
}

export default function StorySandbox() {
    const [isPanelOpen, setIsPanelOpen] = useState(true);
    const [editorContent, setEditorContent] = useState('');
    const [beatInput, setBeatInput] = useState('');
    const textareaRef = useRef(null);
    const streamingRef = useRef('');

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

    const [activeChapterId, setActiveChapterId] = useState(null);
    const [isStreaming, setIsStreaming] = useState(false);
    const [deleteConfirm, setDeleteConfirm] = useState(null);

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
            setActiveChapterId(chapters[0].id);
        }
    }, [chapters, activeChapterId]);

    // Load chapter content into editor
    useEffect(() => {
        if (activeChapter) {
            setEditorContent(activeChapter.content || '');
            streamingRef.current = '';
        }
    }, [activeChapterId, activeChapter]);

    // WebSocket for streaming story continuation
    useEffect(() => {
        const unsubProgress = subscribe(EventTypes.JOB_PROGRESS, (event) => {
            const job = event.data?.job || event;
            if (job.metadata_?.story_id === activeStoryId && job.metadata_?.chapter_id === activeChapterId) {
                const streamText = job.metadata_?.text || job.output?.text || job.progress_text;
                if (streamText) {
                    setIsStreaming(true);
                    streamingRef.current = streamText;
                    setEditorContent((activeChapter?.content || '') + '\n\n' + streamText);
                }
            }
        });

        const unsubCompleted = subscribe(EventTypes.JOB_COMPLETED, (event) => {
            const job = event.data?.job || event;
            if (job.metadata_?.story_id === activeStoryId && job.metadata_?.chapter_id === activeChapterId) {
                setIsStreaming(false);
                streamingRef.current = '';
                queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
                if (job.id) {
                    useWorldVaultStore.getState().clearStreamingJob(job.id);
                }
            }
        });

        return () => {
            unsubProgress();
            unsubCompleted();
        };
    }, [subscribe, activeStoryId, activeChapterId, activeChapter?.content, queryClient]);

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
        try {
            await continueChapter.mutateAsync({ storyId: activeStoryId, chapterId: activeChapterId });
            toast('AI is continuing the story...', { icon: '📖' });
        } catch {
            toast.error('Failed to start story continuation');
            setIsStreaming(false);
        }
    }, [activeStoryId, activeChapterId, isStreaming, continueChapter]);

    const handleAddBeat = useCallback(async () => {
        if (!beatInput.trim() || !activeStoryId || !activeChapterId) return;
        try {
            await addStoryBeat.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                content: beatInput.trim()
            });
            setBeatInput('');
            queryClient.invalidateQueries({ queryKey: ['world_vault', 'stories', activeStoryId, 'chapters'] });
            toast.success('Beat added');
        } catch {
            toast.error('Failed to add beat');
        }
    }, [beatInput, activeStoryId, activeChapterId, addStoryBeat, queryClient]);

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
            className="flex h-[calc(100vh-8rem)] lg:h-[calc(100vh-4rem)] -mx-2 sm:-mx-4 lg:-mx-8 -my-3 sm:-my-4 lg:-my-8 bg-[#0B0E14]"
        >
            {/* Stories Sidebar */}
            <StorySidebar
                stories={stories}
                activeStoryId={activeStoryId}
                onSelectStory={(id) => { setActiveStory(id); setActiveChapterId(null); }}
                onCreateStory={handleCreateStory}
                onDeleteStory={handleDeleteStory}
                isLoading={storiesLoading}
            />

            {/* Main Editor */}
            <div className="flex-1 flex flex-col min-w-0 relative">
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
                        {/* Chapters Sidebar + Editor in a row */}
                        <div className="flex-1 flex min-h-0">
                            <ChapterSidebar
                                chapters={chapters}
                                activeChapterId={activeChapterId}
                                onSelectChapter={setActiveChapterId}
                                onCreateChapter={handleCreateChapter}
                                onDeleteChapter={handleDeleteChapter}
                                isLoading={chaptersLoading}
                            />

                            {/* Editor Area */}
                            <div className="flex-1 flex flex-col min-w-0">
                                {/* Header */}
                                <div className="h-16 border-b border-white/5 flex items-center justify-between px-6 bg-gray-900/60 backdrop-blur-md z-10 shrink-0">
                                    <div className="flex items-center gap-3">
                                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center">
                                            <BookOpen className="text-indigo-400" size={20} />
                                        </div>
                                        <div>
                                            <input
                                                type="text"
                                                defaultValue={activeStory?.title || ''}
                                                onBlur={handleStoryTitleUpdate}
                                                className="bg-transparent font-semibold text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 rounded px-1 transition-all"
                                            />
                                            <p className="text-xs text-gray-500 px-1">
                                                {activeChapter ? `${activeChapter.title || `Chapter ${activeChapter.chapter_number}`}` : 'Select a chapter'}
                                                {activeStory?.genre && ` · ${activeStory.genre}`}
                                            </p>
                                        </div>
                                    </div>
                                    
                                    <div className="flex items-center gap-2">
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
                                            onClick={() => setIsPanelOpen(!isPanelOpen)}
                                            className={clsx(
                                                "p-2 rounded-lg transition-colors border",
                                                isPanelOpen ? "bg-indigo-500/20 text-indigo-400 border-indigo-500/30" : "bg-white/5 text-gray-400 border-white/5 hover:text-white hover:bg-white/10"
                                            )}
                                        >
                                            <ImageIcon size={20} />
                                        </button>
                                    </div>
                                </div>

                                {/* Editor Content */}
                                <div className="flex-1 overflow-y-auto custom-scrollbar flex justify-center p-6 lg:p-12">
                                    {!activeChapterId ? (
                                        <div className="flex items-center justify-center text-gray-500">
                                            <p className="text-sm">Select or create a chapter to start writing</p>
                                        </div>
                                    ) : (
                                        <div className="w-full max-w-3xl relative">
                                            <textarea
                                                ref={textareaRef}
                                                value={editorContent}
                                                onChange={(e) => setEditorContent(e.target.value)}
                                                className="w-full bg-transparent text-gray-300 text-lg md:text-xl leading-relaxed font-serif focus:outline-none resize-none min-h-[300px]"
                                                placeholder="Begin your story here..."
                                                disabled={isStreaming}
                                            />
                                            
                                            {isStreaming && (
                                                <div className="flex items-center gap-2 text-indigo-400 font-serif mt-4 animate-pulse">
                                                    <Sparkles size={16} />
                                                    <span>The AI is weaving the next thread...</span>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>

                                {/* Beat Input */}
                                {activeChapterId && (
                                    <div className="px-6 pb-2">
                                        <div className="max-w-3xl mx-auto flex gap-2">
                                            <input
                                                type="text"
                                                value={beatInput}
                                                onChange={e => setBeatInput(e.target.value)}
                                                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAddBeat(); } }}
                                                placeholder="Add a story beat (narrator direction, user action, system event)..."
                                                className="flex-1 bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500/50 transition-all"
                                                disabled={addStoryBeat.isPending}
                                            />
                                            <button
                                                onClick={handleAddBeat}
                                                disabled={!beatInput.trim() || addStoryBeat.isPending}
                                                className="px-4 py-2 text-sm bg-indigo-500/20 text-indigo-300 rounded-lg hover:bg-indigo-500/30 transition-colors disabled:opacity-30"
                                            >
                                                {addStoryBeat.isPending ? <Loader2 size={14} className="animate-spin" /> : 'Add Beat'}
                                            </button>
                                        </div>
                                    </div>
                                )}

                                {/* Floating Action Bar */}
                                {activeChapterId && (
                                    <motion.div 
                                        initial={{ y: 50, opacity: 0, x: '-50%' }}
                                        animate={{ y: 0, opacity: 1, x: '-50%' }}
                                        className="absolute bottom-6 left-1/2 flex items-center gap-2 p-2 rounded-2xl bg-gray-900/80 backdrop-blur-xl border border-white/10 shadow-2xl shadow-indigo-500/10"
                                    >
                                        <div className="w-px h-8 bg-white/10 mx-1" />
                                        <motion.button
                                            onClick={handleContinue}
                                            disabled={isStreaming || continueChapter.isPending}
                                            whileHover={{ scale: (isStreaming || continueChapter.isPending) ? 1 : 1.05 }}
                                            whileTap={{ scale: (isStreaming || continueChapter.isPending) ? 1 : 0.95 }}
                                            className={clsx(
                                                "flex items-center gap-2 px-6 py-3 rounded-xl font-medium transition-all relative overflow-hidden",
                                                isStreaming || continueChapter.isPending
                                                    ? "bg-indigo-500/50 text-white/50 cursor-not-allowed"
                                                    : "bg-indigo-600 text-white shadow-[0_0_20px_rgba(79,70,229,0.4)] hover:shadow-[0_0_30px_rgba(79,70,229,0.8)]"
                                            )}
                                        >
                                            {/* Glow effect */}
                                            {!(isStreaming || continueChapter.isPending) && (
                                                <motion.div 
                                                    className="absolute inset-0 bg-white/20"
                                                    initial={{ x: '-100%', opacity: 0 }}
                                                    animate={{ x: '100%', opacity: 0 }}
                                                    transition={{ repeat: Infinity, duration: 2, ease: 'linear', repeatDelay: 1 }}
                                                    whileHover={{ opacity: 1 }}
                                                />
                                            )}
                                            {isStreaming || continueChapter.isPending ? (
                                                <div className="flex items-center gap-2">
                                                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                                    Generating
                                                </div>
                                            ) : (
                                                <>
                                                    <Play size={18} fill="currentColor" className="opacity-80" />
                                                    Continue
                                                </>
                                            )}
                                        </motion.button>
                                        <div className="w-px h-8 bg-white/10 mx-1" />
                                    </motion.div>
                                )}
                            </div>
                        </div>
                    </>
                )}
            </div>

            {/* Right Panel: Illustrations & Settings */}
            <AnimatePresence initial={false}>
                {isPanelOpen && activeStoryId && (
                    <motion.div
                        initial={{ width: 0, opacity: 0 }}
                        animate={{ width: 360, opacity: 1 }}
                        exit={{ width: 0, opacity: 0 }}
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                        className="hidden lg:flex flex-col border-l border-white/5 bg-gray-900/40 overflow-hidden shrink-0 relative"
                    >
                        <div className="h-16 border-b border-white/5 flex items-center px-4 shrink-0 bg-gray-900/60 backdrop-blur-md">
                            <h3 className="font-semibold text-gray-200 flex items-center gap-2">
                                <ImageIcon size={16} className="text-indigo-400" />
                                Story Context
                            </h3>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto p-4 custom-scrollbar space-y-4">
                            {/* Active Lorebooks */}
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

                            {/* Chapter Images */}
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

                            {/* Story Info */}
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
        </motion.div>
    );
}
