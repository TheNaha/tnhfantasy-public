import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useParams, useNavigate } from 'react-router-dom';
import { BookOpen, Edit3, Layers } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useStories, useStory, useStoryChapters, useCreateStory, useCreateChapter, useContinueChapter, useBranchChapter, useAddStoryBeat, useLorebooks, useCharacters, useDeleteStory, useDeleteChapter, useUpdateChapter, useUpdateStory, useIllustrateChapter, useLLMAvailableModels, useLLMDefaultProvider, useStoryImages, useUpdateCharacter, useParseStory, usePublishStory, useNarrateChapter } from '../hooks/useWorldVault';
import { useLLMJobResult } from '../hooks/useLLMJobResult';
import { useWebSocket, EventTypes } from '../api/websocket';
import { useQueryClient } from '@tanstack/react-query';
import { clearStreamingJob } from '../hooks/useStreamingJobs';
import { useStoryStreaming } from '../hooks/useStoryStreaming';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';
import { useCollections } from '../hooks/useCollections';
import { addImagesToCollection } from '../api/collectionsApi';
import BottomTabBar from '../components/BottomTabBar';
import StorySidebar from '../components/story/StorySidebar';
import ChapterSidebar from '../components/story/ChapterSidebar';
import StoryHeader from '../components/story/StoryHeader';
import StoryEditor from '../components/story/StoryEditor';
import StoryBeatsPanel from '../components/story/StoryBeatsPanel';
import StoryActionBar from '../components/story/StoryActionBar';
import ExportModal from '../components/story/ExportModal';
import StoryContextPanel from '../components/story/StoryContextPanel';
import CreateStoryModal from '../components/story/CreateStoryModal';
import IllustrateModal from '../components/story/IllustrateModal';
import StoryGalleryModal from '../components/story/StoryGalleryModal';
import ParseStoryModal from '../components/story/ParseStoryModal';
import { CharacterModal } from './Characters';
import { LorebookModal } from '../components/story/LorebookModal';

export default function StorySandbox() {
    // Only default the context panel open on desktop — on phones/tablets the
    // panel is an overlay tab, so don't mount (and animate) it on every visit.
    const [isPanelOpen, setIsPanelOpen] = useState(() => typeof window !== 'undefined' && window.innerWidth >= 1024);
    const [editorContent, setEditorContent] = useState('');
    const [beatInput, setBeatInput] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [showParseModal, setShowParseModal] = useState(false);
    const [newStoryTitle, setNewStoryTitle] = useState('');
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
    const parseStory = useParseStory();
    const publishStory = usePublishStory();
    const narrateChapter = useNarrateChapter();

    const [isExportModalOpen, setIsExportModalOpen] = useState(false);
    const wordCount = useMemo(() => {
        const text = editorContent || '';
        const trimmed = text.trim();
        if (!trimmed) return 0;
        return trimmed.split(/\s+/).length;
    }, [editorContent]);

    const readingTimeMinutes = useMemo(() => {
        return Math.max(1, Math.ceil(wordCount / 200));
    }, [wordCount]);

    const {
        isStreaming,
        setIsStreaming,
        isIllustrating,
        setIsIllustrating,
        streamingBaseRef,
        isStreamingRef
    } = useStoryStreaming({
        activeStoryId,
        activeChapterId,
        setEditorContent,
        isDirtyRef
    });

    const [illustratePrompt, setIllustratePrompt] = useState('');
    const [showIllustrateModal, setShowIllustrateModal] = useState(false);
    const [showGallery, setShowGallery] = useState(false);
    const [editingCharacter, setEditingCharacter] = useState(null);
    const [editingLorebook, setEditingLorebook] = useState(null);

    const updateCharacter = useUpdateCharacter();

    const handleSaveCharacter = async (form) => {
        const { _avatarFile, ...payload } = form;
        if (editingCharacter) {
            await updateCharacter.mutateAsync({ id: editingCharacter.id, ...payload });
            setEditingCharacter(null);
        }
    };

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

    useEffect(() => {
        const handler = () => setShowParseModal(true);
        window.addEventListener('open-parse-story', handler);
        return () => window.removeEventListener('open-parse-story', handler);
    }, []);

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

    const handleParseStoryComplete = async (text) => {
        setShowParseModal(false);
        try {
            const titleMatch = text.trim().split('\n')[0].substring(0, 50).replace(/[^\w\s-]/gi, '').trim();
            const title = titleMatch ? titleMatch : 'Imported Story';
            
            const newStory = await createStory.mutateAsync({ title });
            await updateChapter.mutateAsync({ 
                storyId: newStory.id, 
                chapterId: newStory.chapters?.[0]?.id || '1', 
                updates: { content: text }
            });
            
            await parseStory.mutateAsync({ storyId: newStory.id, text });
            
            navigate(`/story/${newStory.id}`, { replace: true });
            
            toast.success("Story imported. AI is parsing Characters & Lore in the background!");
        } catch (err) {
            console.error(err);
            toast.error("Failed to import story.");
        }
    };



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
            await updateChapter.mutateAsync({ storyId: activeStoryId, chapterId: activeChapterId, title: newTitle });
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

    const handleCreateStoryFromModal = async () => {
        const title = newStoryTitle.trim();
        if (!title) return;
        try {
            await handleCreateStory({ title });
            setNewStoryTitle('');
            setShowCreateModal(false);
        } catch {
            toast.error('Failed to create story');
        }
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

    const handleExportStory = useCallback(() => {
        if (!activeStoryId) return;
        setIsExportModalOpen(true);
    }, [activeStoryId]);

    const handlePublishStory = useCallback(() => {
        if (!activeStoryId) return;
        publishStory.mutate({ storyId: activeStoryId }, {
            onSuccess: (data) => {
                toast.success('Story published!');
                if (data?.read_url) {
                    navigator.clipboard.writeText(window.location.origin + data.read_url);
                    toast('Shareable link copied to clipboard!', { icon: '🔗' });
                }
            },
            onError: (e) => toast.error(`Publish failed: ${e.message}`),
        });
    }, [activeStoryId, publishStory]);

    const handleNarrateChapter = useCallback((chapterId) => {
        if (!activeStoryId) return;
        narrateChapter.mutate({ storyId: activeStoryId, chapterId }, {
            onSuccess: () => toast.success('Narration job queued'),
            onError: (e) => toast.error(`Narration failed: ${e.message}`),
        });
    }, [activeStoryId, narrateChapter]);

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
            await updateStory.mutateAsync({ id: activeStoryId, title: newTitle });
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
            className="flex flex-col h-full bg-[#0B0E14]"
        >
            <div className="flex flex-1 min-h-0 relative">
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
                {!activeStoryId ? (
                    <>
                        <div className="flex-1 flex items-center justify-center">
                            <EmptyState
                                title="No Story Selected"
                                description="Select a story from the sidebar or create a new one to start writing."
                                primaryLabel="Create Story"
                                primaryAction={() => setShowCreateModal(true)}
                            />
                        </div>
                        {showCreateModal && (
                            <CreateStoryModal
                                title={newStoryTitle}
                                onTitleChange={setNewStoryTitle}
                                onConfirm={handleCreateStoryFromModal}
                                onClose={() => { setShowCreateModal(false); setNewStoryTitle(''); }}
                            />
                        )}
                        <ParseStoryModal
                            isOpen={showParseModal}
                            onClose={() => setShowParseModal(false)}
                            onComplete={handleParseStoryComplete}
                        />

                        {editingCharacter && (
                            <CharacterModal
                                isOpen={true}
                                onClose={() => setEditingCharacter(null)}
                                character={editingCharacter}
                                onSave={handleSaveCharacter}
                            />
                        )}

                        <LorebookModal
                            isOpen={!!editingLorebook}
                            onClose={() => setEditingLorebook(null)}
                            lorebook={editingLorebook}
                        />
                    </>
                ) : (
                    <>
                        <div className="flex-1 flex min-h-0 relative">
                            <div className={clsx(
                                "flex-1 flex flex-col min-w-0",
                                mobileTab === 'write' ? "flex" : "hidden lg:flex"
                            )}>
                                <StoryHeader
                                    activeStory={activeStory}
                                    activeChapter={activeChapter}
                                    activeChapterId={activeChapterId}
                                    isGeneratingTitle={isGeneratingTitle}
                                    onAutoGenerateTitle={handleAutoGenerateTitle}
                                    isSaving={updateChapter.isPending}
                                    onSave={handleSaveChapter}
                                    isStreaming={isStreaming}
                                    isPreviewMode={isPreviewMode}
                                    onTogglePreview={() => setIsPreviewMode(!isPreviewMode)}
                                    isPanelOpen={isPanelOpen}
                                    onTogglePanel={() => setIsPanelOpen(!isPanelOpen)}
                                    mobileTab={mobileTab}
                                    onOpenContextMobile={() => { setIsPanelOpen(!isPanelOpen); setMobileTab('context'); }}
                                    onTitleChange={handleStoryTitleUpdate}
                                    onExport={handleExportStory}
                                />
                                <StoryEditor
                                    isPreviewMode={isPreviewMode}
                                    editorContent={editorContent}
                                    onEditorChange={(v) => { isDirtyRef.current = true; setEditorContent(v); }}
                                    textareaRef={textareaRef}
                                    isStreaming={isStreaming}
                                    activeChapterId={activeChapterId}
                                    wordCount={wordCount}
                                    readingTimeMinutes={readingTimeMinutes}
                                />
                                {activeChapterId && (
                                    <div className="px-2 sm:px-4 lg:px-6 pb-4 pt-2 border-t border-white/5 bg-gray-900/40 shrink-0">
                                        {showBeatsPanel && (
                                            <StoryBeatsPanel
                                                beats={activeChapter?.beats || []}
                                                isStreaming={isStreaming}
                                                branchingBeatId={branchingBeatId}
                                                branchPending={branchChapter.isPending}
                                                onBranch={handleBranchFromBeat}
                                                onClose={() => setShowBeatsPanel(false)}
                                            />
                                        )}
                                        <StoryActionBar
                                            beatCount={(activeChapter?.beats || []).length}
                                            showBeatsPanel={showBeatsPanel}
                                            onToggleBeats={() => setShowBeatsPanel(!showBeatsPanel)}
                                            isStreaming={isStreaming}
                                            isContinuePending={continueChapter.isPending}
                                            onContinue={handleContinue}
                                            isIllustrating={isIllustrating}
                                            onIllustrate={handleIllustrate}
                                            beatInput={beatInput}
                                            onBeatInputChange={setBeatInput}
                                            onAddBeat={handleAddBeat}
                                            onExport={handleExportStory}
                                            onPublish={handlePublishStory}
                                            isPublished={activeStory?.is_published}
                                            onNarrate={handleNarrateChapter}
                                            activeChapterId={activeChapter?.id}
                                        />
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
                        <StoryContextPanel
                            activeStory={activeStory}
                            activeChapter={activeChapter}
                            characters={characters}
                            lorebooks={lorebooks}
                            storyImages={storyImages}
                            chapters={chapters}
                            llmModels={llmModels}
                            defaultLlmConfig={defaultLlmConfig}
                            onClose={() => { setMobileTab('write'); setIsPanelOpen(false); }}
                            onShowGallery={() => setShowGallery(true)}
                            onUpdateStory={(updates) => { if (activeStoryId) updateStory.mutate({ id: activeStoryId, ...updates }); }}
                            onEditCharacter={setEditingCharacter}
                            onEditLorebook={setEditingLorebook}
                        />
                    </motion.div>
                )}
            </AnimatePresence>

            <IllustrateModal
                open={showIllustrateModal}
                prompt={illustratePrompt}
                onPromptChange={setIllustratePrompt}
                onConfirm={handleConfirmIllustrate}
                onClose={() => { setShowIllustrateModal(false); setIllustratePrompt(''); }}
            />

            <StoryGalleryModal
                open={showGallery}
                storyTitle={activeStory?.title}
                images={storyImages.map(img => img.path)}
                collectionsList={collectionsList}
                onSaveToCollection={handleSaveImageToCollection}
                onClose={() => setShowGallery(false)}
            />

            {/* Shared mobile bottom tab bar for the StorySandbox workspaces. */}
            </div>

            <ExportModal
                story={activeStory}
                storyId={activeStoryId}
                isOpen={isExportModalOpen}
                onClose={() => setIsExportModalOpen(false)}
            />

            <BottomTabBar
                inline
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
