import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useParams, useNavigate } from 'react-router-dom';
import { BookOpen, Edit3, Layers } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useStories, useStory, useStoryChapters, useCreateStory, useCreateChapter, useContinueChapter, useBranchChapter, useAddStoryBeat, useLorebooks, useCharacters, useLocations, useDeleteStory, useDeleteChapter, useUpdateChapter, useUpdateStory, useIllustrateChapter, useLLMAvailableModels, useLLMDefaultProvider, useStoryImages, useUpdateCharacter, useParseStory, usePublishStory, useNarrateChapter, useReorderChapters, useStoryAiAction, useRetryLastContinuation, useUpdateStoryBeat, useDeleteStoryBeat, useChapterRevisions, useCreateChapterRevision, useRestoreChapterRevision, useScenarios } from '../hooks/useWorldVault';
import { useLLMJobResult, awaitJobText } from '../hooks/useLLMJobResult';

import { useQueryClient } from '@tanstack/react-query';
import { useStoryStreaming } from '../hooks/useStoryStreaming';
import EmptyState from '../components/EmptyState';
import { useConfirmation } from '../store/confirmationStore';
import { useCollections } from '../hooks/useCollections';
import { addImagesToCollection } from '../api/collectionsApi';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
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
import { useWorlds } from '../hooks/useWorlds';
import { warnIfWorldIgnored, WORLD_IGNORED_MESSAGE } from '../utils/worldLinkWarning';
import { copyToClipboard } from '../utils/clipboard';
import IllustrateModal from '../components/story/IllustrateModal';
import StoryActionModal from '../components/story/StoryActionModal';
import ChapterRevisionsModal from '../components/story/ChapterRevisionsModal';
import StoryGalleryModal from '../components/story/StoryGalleryModal';
import ParseStoryModal from '../components/story/ParseStoryModal';
import { CharacterModal } from './Characters';
import { LorebookModal } from '../components/story/LorebookModal';
import { LocationModal } from '../components/story/LocationModal';

export default function StorySandbox() {
    // Only default the context panel open on desktop — on phones/tablets the
    // panel is an overlay tab, so don't mount (and animate) it on every visit.
    const [isPanelOpen, setIsPanelOpen] = useState(() => typeof window !== 'undefined' && window.innerWidth >= 1024);
    const [editorContent, setEditorContent] = useState('');
    const [beatInput, setBeatInput] = useState('');
    const [beatRole, setBeatRole] = useState('user');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [showParseModal, setShowParseModal] = useState(false);
    const [newStoryTitle, setNewStoryTitle] = useState('');
    const [newStoryWorldId, setNewStoryWorldId] = useState('');
    const textareaRef = useRef(null);
    const isDirtyRef = useRef(false);
    const loadedChapterIdRef = useRef(null);

    const queryClient = useQueryClient();
    const { storyId: urlStoryId, chapterId: urlChapterId } = useParams();
    const navigate = useNavigate();
    const activeStoryId = urlStoryId || null;
    const activeChapterId = urlChapterId || null;

    const { data: stories = [], isLoading: storiesLoading } = useStories();
    // `isError`/`error`/`refetch` below are load-bearing, and this is the story
    // surface's copy of the defect fixed in `useChatWorkspaceData.js`: each of
    // these six queries destructured `data` with a `= []` default and no
    // `isError`, and `StoryContextPanel` builds "No lorebooks" / "No
    // locations" straight off those arrays. A 503 therefore told the author of
    // a story built on four lorebooks that they had none. `queryErrors` is
    // passed down instead of an `isErrored` boolean because the panel gates
    // five different arrays and each needs its own noun.
    const { data: worlds = [], isError: isWorldsError, error: worldsError, refetch: refetchWorlds } = useWorlds();
    const { data: activeStory } = useStory(activeStoryId);
    const { data: chapters = [], isLoading: chaptersLoading } = useStoryChapters(activeStoryId);
    const { data: lorebooks = [], isError: isLorebooksError, error: lorebooksError, refetch: refetchLorebooks } = useLorebooks();
    const { data: characters = [], isError: isCharactersError, error: charactersError, refetch: refetchCharacters } = useCharacters();
    const {
        data: locations = [], isError: isLocationsError, error: locationsError, refetch: refetchLocations,
    } = useLocations();
    // For the story context panel's Scenario row: Apply writes
    // `Story.scenario_id`, and the panel needs the name to show what was applied.
    const {
        data: scenarios = [], isError: isScenariosError, error: scenariosError, refetch: refetchScenarios,
    } = useScenarios();
    const { data: storyImages = [] } = useStoryImages(activeStoryId);
    const { data: collectionsMap = {} } = useCollections('story');
    // Memoised: this page re-renders on every streamed token.
    const collectionsList = useMemo(
        () => Object.values(collectionsMap).sort((a, b) => (a.name || '').localeCompare(b.name || '')),
        [collectionsMap]
    );

    // One entry per FAILED context query. Built here, at the same choke point
    // as the destructuring above, and handed to `StoryContextPanel` whole — the
    // panel receives arrays and cannot reach a query object itself, which is why
    // `rg "isError|QueryErrorState|QueryGate"` over it returned nothing. Same
    // shape as the chat surface's `useChatWorkspaceData` `queryErrors`.
    const queryErrors = useMemo(() => {
        const map = {};
        const failures = [
            ['worlds', 'worlds', isWorldsError, worldsError, refetchWorlds],
            ['lorebooks', 'lorebooks', isLorebooksError, lorebooksError, refetchLorebooks],
            ['characters', 'characters', isCharactersError, charactersError, refetchCharacters],
            ['locations', 'locations', isLocationsError, locationsError, refetchLocations],
            ['scenarios', 'scenarios', isScenariosError, scenariosError, refetchScenarios],
        ];
        for (const [key, noun, isError, error, refetch] of failures) {
            if (isError) map[key] = { error, refetch, noun };
        }
        return map;
    }, [
        isWorldsError, worldsError, refetchWorlds,
        isLorebooksError, lorebooksError, refetchLorebooks,
        isCharactersError, charactersError, refetchCharacters,
        isLocationsError, locationsError, refetchLocations,
        isScenariosError, scenariosError, refetchScenarios,
    ]);

    const createStory = useCreateStory();
    const createChapter = useCreateChapter();
    const continueChapter = useContinueChapter();
    const branchChapter = useBranchChapter();
    const addStoryBeat = useAddStoryBeat();
    const deleteStory = useDeleteStory();
    const deleteChapter = useDeleteChapter();
    const updateChapter = useUpdateChapter();
    const reorderChapters = useReorderChapters();
    const illustrateChapter = useIllustrateChapter();
    const storyAiAction = useStoryAiAction();
    const retryLastContinuation = useRetryLastContinuation();
    const restoreRevision = useRestoreChapterRevision();
    const createRevision = useCreateChapterRevision();
    const [revisionsOpen, setRevisionsOpen] = useState(false);
    const chapterRevisions = useChapterRevisions(
        activeStoryId || null,
        revisionsOpen ? activeChapterId : null
    );
    const updateStoryBeat = useUpdateStoryBeat();
    const deleteStoryBeat = useDeleteStoryBeat();
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
    const [lastIllustrationPrompt, setLastIllustrationPrompt] = useState('');
    const [showIllustrateModal, setShowIllustrateModal] = useState(false);
    const [storyAction, setStoryAction] = useState(null);
    const [actionResult, setActionResult] = useState(null);
    const [isActionRunning, setIsActionRunning] = useState(false);
    const [aiDirective, setAiDirective] = useState('');
    const [showGallery, setShowGallery] = useState(false);
    const [editingCharacter, setEditingCharacter] = useState(null);
    const [editingLorebook, setEditingLorebook] = useState(null);
    const [showLorebookModal, setShowLorebookModal] = useState(false);
    const [editingLocation, setEditingLocation] = useState(null);
    const [showLocationModal, setShowLocationModal] = useState(false);

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
    // Cancels the 30x1s title-generation poll when navigating away.
    const titlePollCancelledRef = useRef(false);

    useEffect(() => {
        titlePollCancelledRef.current = true;
     
    }, [activeChapterId]);


    const { data: llmModels = [] } = useLLMAvailableModels();
    const { data: defaultLlmConfig } = useLLMDefaultProvider();
    const updateStory = useUpdateStory();
    const updateStoryMutate = updateStory.mutate;

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

    // Load chapter content into editor, and keep a clean editor in sync with the
    // server.
    useEffect(() => {
        // Guard: don't overwrite editor content while actively streaming
        if (isStreamingRef.current) return;

        const serverContent = activeChapter?.content || '';
        const chapterChanged = loadedChapterIdRef.current !== activeChapterId;

        if (chapterChanged) {
            // Flush the outgoing chapter's pending save BEFORE the buffer is
            // reused for the new one.
            //
            // The auto-save below is a 2s debounce, and its cleanup only
            // clears the timer. So switching chapters inside that window used to
            // destroy the pending write outright: the timer was cancelled, the
            // editor was then overwritten with the new chapter's content, and
            // `isDirtyRef` was reset — the user's last edits to the old chapter
            // were gone, with no error, no toast, and no way to recover. The
            // pending payload lives in a ref specifically so it outlives the
            // timer that would have written it.
            flushPendingSave();
            loadedChapterIdRef.current = activeChapterId;
            isDirtyRef.current = false;
        } else if (isDirtyRef.current) {
            // The user has unsaved work in the buffer. Never clobber it.
            return;
        }

        // Reordering or deleting a beat rewrites the chapter prose server-side.
        // Adopt it, otherwise the editor keeps showing text the server no longer
        // has — the mirror image of the auto-save bug above.
        // Wait for next tick to avoid synchronous cascading renders
        const timer = setTimeout(() => {
            setEditorContent(serverContent);
            streamingBaseRef.current = serverContent;
        }, 0);
        return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeChapterId, activeChapter]);

    const resolveMentionsTimerRef = useRef(null);

    useEffect(() => {
        if (!activeStoryId || !editorContent || !activeStory) return;

        if (resolveMentionsTimerRef.current) clearTimeout(resolveMentionsTimerRef.current);

        resolveMentionsTimerRef.current = setTimeout(() => {
            const regex = /\[([^\]]+)\]\(\/world-vault\?(character|lorebook|location)=([a-f0-9-]+)\)/g;
            const mentions = [];
            let match;
            while ((match = regex.exec(editorContent)) !== null) {
                mentions.push({ type: match[2], id: match[3] });
            }

            const currentCharIds = activeStory.character_ids || [];
            const currentLoreIds = activeStory.lorebook_ids || [];
            const currentLocIds = activeStory.location_ids || [];

            const newCharIds = [...new Set([...currentCharIds, ...mentions.filter(m => m.type === 'character').map(m => m.id)])];
            const newLoreIds = [...new Set([...currentLoreIds, ...mentions.filter(m => m.type === 'lorebook').map(m => m.id)])];
            const newLocIds = [...new Set([...currentLocIds, ...mentions.filter(m => m.type === 'location').map(m => m.id)])];

            const hasChanges =
                newCharIds.length !== currentCharIds.length ||
                newLoreIds.length !== currentLoreIds.length ||
                newLocIds.length !== currentLocIds.length;

            if (hasChanges) {
                updateStoryMutate({
                    id: activeStoryId,
                    character_ids: newCharIds,
                    lorebook_ids: newLoreIds,
                    location_ids: newLocIds,
                });
            }
        }, 800);

        return () => {
            if (resolveMentionsTimerRef.current) clearTimeout(resolveMentionsTimerRef.current);
        };
    }, [editorContent, activeStoryId, activeStory, updateStoryMutate]);

    const handleParseStoryComplete = async (text) => {
        setShowParseModal(false);
        try {
            const titleMatch = text.trim().split('\n')[0].substring(0, 50).replace(/[^\w\s-]/gi, '').trim();
            const title = titleMatch ? titleMatch : 'Imported Story';
            
            const newStory = await createStory.mutateAsync({ title });
            // create_story doesn't create an initial chapter — create one
            // with the full parsed text as content, then let the AI parser
            // extract characters/lorebooks/locations in the background.
            await createChapter.mutateAsync({
                storyId: newStory.id,
                data: { title: 'Chapter 1', content: text },
            });
            
            await parseStory.mutateAsync({ storyId: newStory.id, text });
            
            navigate(`/story/${newStory.id}`, { replace: true });
            
            toast.success("Story imported. AI is parsing Characters & Lore in the background!");
        } catch {
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
    // The chapter content waiting to be written, held separately from the timer
    // that would have written it.
    //
    // Holding it here is what makes the debounce safe to cancel. A debounce is
    // *designed* to drop its work when it is reset, which is right for a search
    // box and catastrophic for an editor: every way this timer could be cleared
    // (chapter switch, story switch, unmount, the Ctrl+S guard) took the user's
    // uncommitted text with it. The ref survives all of them, and
    // `flushPendingSave` writes it on the way out.
    const pendingSaveRef = useRef(null);
    const updateChapterMutateAsync = updateChapter.mutateAsync;

    const flushPendingSave = useCallback(async () => {
        const pending = pendingSaveRef.current;
        if (!pending) return;
        pendingSaveRef.current = null;
        if (autoSaveTimerRef.current) {
            clearTimeout(autoSaveTimerRef.current);
            autoSaveTimerRef.current = null;
        }
        try {
            await updateChapterMutateAsync(pending);
            isDirtyRef.current = false;
        } catch {
            // Put it back so a later flush — or the beforeunload guard — can
            // still try, and tell the user it did not stick.
            pendingSaveRef.current = pending;
            toast.error('Chapter auto-save failed');
        }
    }, [updateChapterMutateAsync]);

    // Unmount, and a browser tab close / reload. React cleanups do not reliably
    // run for a tab being closed, and a story sandbox is exactly where someone
    // has an afternoon of prose they will notice losing. The prompt is
    // suppressed in the common case because by the time this runs the debounce
    // has usually already fired and the ref is empty.
    useEffect(() => {
        const onBeforeUnload = (event) => {
            if (!pendingSaveRef.current) return;
            event.preventDefault();
            // Chrome requires returnValue to be set to trigger the dialog.
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', onBeforeUnload);
        return () => {
            window.removeEventListener('beforeunload', onBeforeUnload);
            flushPendingSave();
        };
    }, [flushPendingSave]);

    useEffect(() => {
        if (!activeChapterId || isStreaming) return;
        // Only a *user* edit may be auto-saved. A buffer that differs from the
        // server is not necessarily stale local state: reordering or deleting a
        // beat rewrites the chapter prose server-side, and this effect used to
        // PUT the pre-reorder buffer back over that rewrite — silently reverting
        // the surgery, with no user action and no error. `isDirtyRef` is set
        // only by `onEditorChange`, so it distinguishes the two cases exactly.
        if (!isDirtyRef.current) return;
        if (activeChapterId !== loadedChapterIdRef.current) return;

        // The payload is recorded *before* the timer is armed, so it exists even
        // if this effect is cleaned up in the same tick it ran.
        pendingSaveRef.current = {
            storyId: activeStoryId,
            chapterId: activeChapterId,
            content: editorContent,
        };

        autoSaveTimerRef.current = setTimeout(() => {
            // The timer only proposes. `flushPendingSave` re-checks that the
            // payload still belongs to the chapter the editor is showing, so a
            // timer that fires after a switch writes nothing rather than
            // writing the old chapter's text over the new one.
            if (
                pendingSaveRef.current?.chapterId !== loadedChapterIdRef.current
                || isStreamingRef.current
            ) {
                return;
            }
            flushPendingSave();
        }, 2000);

        // Cancel the timer only. The payload stays in `pendingSaveRef` and is
        // written by `flushPendingSave` on the way out — from the chapter-change
        // branch above, or from unmount. Clearing the payload here as well is
        // what lost the text.
        return () => clearTimeout(autoSaveTimerRef.current);
    // Depend on the stable mutateAsync reference, not the mutation result
    // object: react-query v5 returns a new object literal from useMutation on
    // every render, so including it cleared the timer and restarted the 2s
    // window on every background re-render (queue poll, WS isIllustrating,
    // revisions refetch) and the save could never fire.
    //
    // `activeChapter?.content` is deliberately NOT a dependency. This effect
    // must react to local edits only; re-running it because the server changed
    // the chapter is what turned every server-side prose rewrite into a
    // destructive write-back.
    }, [editorContent, activeChapterId, isStreaming, activeStoryId, flushPendingSave]);

    const handleContinue = useCallback(async () => {
        if (!activeStoryId || !activeChapterId || isStreaming) return;
        setIsStreaming(true);
        streamingBaseRef.current = editorContent;
        try {
            await continueChapter.mutateAsync({ storyId: activeStoryId, chapterId: activeChapterId, prompt: aiDirective.trim() });
            setAiDirective('');
            toast('AI is continuing the story...', { icon: '📖' });
        } catch {
            toast.error('Failed to start story continuation');
            setIsStreaming(false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeStoryId, activeChapterId, isStreaming, continueChapter, editorContent, aiDirective]);

    const captureEditorSelection = useCallback(() => {
        if (textareaRef.current) {
            const { selectionStart: s, selectionEnd: e, value } = textareaRef.current;
            if (s !== e) return { start: s, end: e, text: value.substring(s, e) };
        }
        return null;
    }, []);

    const handleOpenStoryAction = useCallback((action) => {
        if (!activeStoryId || !activeChapterId || isStreaming || isActionRunning) return;
        const sel = captureEditorSelection();
        if (!sel && action !== 'summarize') {
            toast.error('Select some text in the editor first');
            return;
        }
        setStoryAction({
            action,
            start: sel?.start ?? editorContent.length,
            end: sel?.end ?? editorContent.length,
            selectionText: sel ? sel.text : editorContent,
            directive: '',
        });
        setActionResult(null);
     
    }, [activeStoryId, activeChapterId, isStreaming, isActionRunning, captureEditorSelection, editorContent]);

    const handleConfirmStoryAction = useCallback(async () => {
        if (!storyAction || isActionRunning || !activeStoryId || !activeChapterId) return;
        setIsActionRunning(true);
        try {
            const { job_id } = await storyAiAction.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                action: storyAction.action,
                target_text: storyAction.selectionText,
                directive: storyAction.directive,
            });
            const { text } = await awaitJobText({ jobId: job_id, queryClient });
            if (!text) {
                toast.error('AI returned no text');
                return;
            }
            setActionResult(text.trim());
        } catch {
            toast.error('AI action failed');
        } finally {
            setIsActionRunning(false);
        }
     
    }, [storyAction, isActionRunning, activeStoryId, activeChapterId, storyAiAction, queryClient]);

    const handleCloseStoryAction = useCallback(() => {
        if (isActionRunning) return;
        setStoryAction(null);
        setActionResult(null);
    }, [isActionRunning]);

    const handleApplyStoryAction = useCallback((insertAtCursor = false) => {
        if (!storyAction || !actionResult) return;
        const { action, start, end } = storyAction;
        let next;
        if ((action === 'rewrite' || action === 'expand') && !insertAtCursor) {
            next = editorContent.slice(0, start) + actionResult + editorContent.slice(end);
        } else {
            const pos = Math.min(start, editorContent.length);
            const sepBefore = pos > 0 && !/\n\n$/.test(editorContent.slice(0, pos)) ? '\n\n' : '';
            next = editorContent.slice(0, pos) + sepBefore + actionResult + '\n\n' + editorContent.slice(pos);
        }
        next = next.replace(/\n{4,}/g, '\n\n\n');
        isDirtyRef.current = true;
        setEditorContent(next);
        streamingBaseRef.current = next;
        setStoryAction(null);
        setActionResult(null);
        toast.success('Applied to chapter');
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [storyAction, actionResult, editorContent]);

    const handleRetryLast = useCallback(async () => {
        if (!activeStoryId || !activeChapterId || isStreaming || retryLastContinuation.isPending) return;
        const ok = await confirm({
            title: 'Retry Last Continuation',
            message: "Discard the AI's most recent continuation and generate a fresh one?",
            confirmText: 'Retry',
        });
        if (!ok) return;
        try {
            await retryLastContinuation.mutateAsync({ storyId: activeStoryId, chapterId: activeChapterId });
            const key = buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'chapters');
            await queryClient.invalidateQueries({ queryKey: key });
            const data = queryClient.getQueryData(key);
            const fresh = Array.isArray(data) ? data.find(ch => ch.id === activeChapterId) : null;
            const trimmed = fresh?.content ?? '';
            isDirtyRef.current = false;
            setEditorContent(trimmed);
            streamingBaseRef.current = trimmed;
            setIsStreaming(true);
            toast('Retrying continuation...', { icon: '🔁' });
        } catch {
            toast.error('Failed to retry last continuation');
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeStoryId, activeChapterId, isStreaming, retryLastContinuation, confirm, queryClient]);

    const handleSaveRevision = useCallback(async () => {
        if (!activeStoryId || !activeChapterId || createRevision.isPending) return;
        try {
            await createRevision.mutateAsync({ storyId: activeStoryId, chapterId: activeChapterId });
            toast.success('Snapshot saved');
        } catch {
            toast.error('Failed to save snapshot');
        }
    }, [activeStoryId, activeChapterId, createRevision]);

    const handleRestoreRevision = useCallback(async (rev) => {
        if (!activeStoryId || !activeChapterId || restoreRevision.isPending) return;
        const ok = await confirm({
            title: 'Restore Revision',
            message: 'Replace the current chapter prose with this snapshot? The current text is snapshotted first, so this can be undone.',
            confirmText: 'Restore',
        });
        if (!ok) return;
        try {
            await restoreRevision.mutateAsync({ storyId: activeStoryId, chapterId: activeChapterId, revisionId: rev.id });
            const key = buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'chapters');
            await queryClient.invalidateQueries({ queryKey: key });
            const data = queryClient.getQueryData(key);
            const fresh = Array.isArray(data) ? data.find(ch => ch.id === activeChapterId) : null;
            const restored = fresh?.content ?? '';
            isDirtyRef.current = false;
            setEditorContent(restored);
            streamingBaseRef.current = restored;
            setRevisionsOpen(false);
            toast.success('Revision restored');
        } catch {
            toast.error('Failed to restore revision');
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeStoryId, activeChapterId, restoreRevision, confirm, queryClient]);

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
            const snippet = beatRole === 'user' ? `\n\n> ${newBeat}\n\n` : `\n\n${newBeat}\n\n`;
            const newContent = editorContent ? editorContent.replace(/\n+$/, '') + snippet : snippet;
            setEditorContent(newContent);
            streamingBaseRef.current = newContent;

            await addStoryBeat.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                content: newBeat,
                role: beatRole,
            });
            setBeatInput('');
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'chapters') });
            toast.success('Beat added');
        } catch {
            toast.error('Failed to add beat');
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [beatInput, beatRole, activeStoryId, activeChapterId, addStoryBeat, queryClient, editorContent]);

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
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'chapters') });
            navigate(`/story/${activeStoryId}/chapter/${branch.id}`);
            toast.success('Branch created');
        } catch {
            toast.error('Failed to create branch');
        } finally {
            setBranchingBeatId(null);
        }
     
    }, [activeStoryId, activeChapterId, isStreaming, branchChapter, confirm, queryClient, navigate]);

    const handleReorderBeats = useCallback(async (newBeats) => {
        if (!activeStoryId || !activeChapterId || isStreaming) return;
        try {
            await updateChapter.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                beats: newBeats,
            });
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'chapters') });
            toast.success('Beats reordered');
        } catch {
            toast.error('Failed to reorder beats');
        }
    }, [activeStoryId, activeChapterId, isStreaming, updateChapter, queryClient]);

    // Mirror the backend's beat-prose surgery locally so the open editor
    // stays in sync with the persisted chapter after a beat edit/delete.
    const syncEditorWithBeat = useCallback((oldContent, oldRole, newContent, newRole) => {
        setEditorContent((prev) => {
            if (!prev) return prev;
            const fmt = (c, r) => (r === 'user' ? `\n\n> ${c}\n\n` : `\n\n${c}\n\n`);
            let next = prev;
            let replaced = false;
            if (newContent != null) {
                const oldSnip = fmt(oldContent, oldRole);
                const i = next.lastIndexOf(oldSnip);
                if (i >= 0) {
                    next = next.slice(0, i) + fmt(newContent, newRole) + next.slice(i + oldSnip.length);
                    replaced = true;
                }
            } else {
                const snip = fmt(oldContent, oldRole);
                const i = next.lastIndexOf(snip);
                if (i >= 0) {
                    next = (next.slice(0, i) + '\n\n' + next.slice(i + snip.length)).trim();
                    replaced = true;
                }
            }
            if (replaced) {
                streamingBaseRef.current = next.replace(/\n{4,}/g, '\n\n\n');
                return streamingBaseRef.current;
            }
            return prev;
        });
    }, [streamingBaseRef]);

    const handleEditBeat = useCallback(async (beatId, patch) => {
        if (!activeStoryId || !activeChapterId || isStreaming) return;
        const beat = (activeChapter?.beats || []).find((b) => b?.id === beatId);
        if (!beat) return;
        try {
            await updateStoryBeat.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                beatId,
                content: patch.content,
                role: patch.role,
            });
            const oldContent = beat.content || '';
            const oldRole = beat.role || 'narrator';
            const newContent = patch.content !== undefined ? patch.content : oldContent;
            const newRole = patch.role !== undefined ? patch.role : oldRole;
            if (newContent !== oldContent || newRole !== oldRole) {
                syncEditorWithBeat(oldContent, oldRole, newContent, newRole);
            }
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'chapters') });
            toast.success('Beat updated');
        } catch (err) {
            toast.error(err?.message || 'Failed to update beat');
        }
    }, [activeStoryId, activeChapterId, activeChapter, isStreaming, updateStoryBeat, syncEditorWithBeat, queryClient]);

    const handleDeleteBeat = useCallback(async (beatId) => {
        if (!activeStoryId || !activeChapterId || isStreaming) return;
        const beat = (activeChapter?.beats || []).find((b) => b?.id === beatId);
        if (!beat) return;
        const ok = await confirm({
            title: 'Delete Beat',
            message: 'Remove this beat and its text from the chapter prose?',
            confirmText: 'Delete',
        });
        if (!ok) return;
        try {
            await deleteStoryBeat.mutateAsync({
                storyId: activeStoryId,
                chapterId: activeChapterId,
                beatId,
            });
            syncEditorWithBeat(beat.content || '', beat.role || 'narrator', null, null);
            queryClient.invalidateQueries({ queryKey: buildQueryKey(QUERY_KEYS.STORIES, activeStoryId, 'chapters') });
            toast.success('Beat deleted');
        } catch (err) {
            toast.error(err?.message || 'Failed to delete beat');
        }
    }, [activeStoryId, activeChapterId, activeChapter, isStreaming, deleteStoryBeat, confirm, syncEditorWithBeat, queryClient]);

    const handleReorderChapters = useCallback(async (newChapters) => {
        if (!activeStoryId || reorderChapters.isPending) return;
        try {
            await reorderChapters.mutateAsync({
                storyId: activeStoryId,
                chapterIds: newChapters.map(c => c.id),
            });
            toast.success('Chapters reordered');
        } catch {
            toast.error('Failed to reorder chapters');
        }
    }, [activeStoryId, reorderChapters]);

    const handleCreateStory = async (data) => {
        return createStory.mutateAsync(data);
    };

    const handleCreateStoryFromModal = async () => {
        const title = newStoryTitle.trim();
        if (!title) return;
        try {
            // `world_id` is sent whenever a world was picked. `Story.world_id`
            // is a real column and comes back on the created story, so the
            // response is the capability check: a server that does not accept
            // the field yet drops it, and the story is created regardless. The
            // warning is what keeps that from being silent.
            const story = await handleCreateStory(newStoryWorldId ? { title, world_id: newStoryWorldId } : { title });
            if (warnIfWorldIgnored(story, newStoryWorldId, 'story')) toast(WORLD_IGNORED_MESSAGE('story'));
            setNewStoryTitle('');
            setNewStoryWorldId('');
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
            onSuccess: async (data) => {
                // The publish and the copy are two facts with two answers.
                toast.success('Story published!');
                // `await`, not `.then()`: on a non-secure origin the
                // `navigator.clipboard` dereference throws SYNCHRONOUSLY, so
                // there is no promise for `.then`/`.catch` to attach to and the
                // "Shareable link copied" toast below was unreachable — while
                // the "Story published!" toast above it had already fired.
                // Measured: `http://100.150.0.4:5174` → `{"secure":false,
                // "clip":false}`.
                if (data?.read_url) {
                    const copied = await copyToClipboard(window.location.origin + data.read_url);
                    if (copied) {
                        toast('Shareable link copied to clipboard!', { icon: '🔗' });
                    } else {
                        toast.error('Story published, but the link could not be copied on this address.');
                    }
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
        const ok = await confirm({
            title: 'Delete Chapter',
            message: 'This permanently removes the chapter and its content. This cannot be undone.',
            confirmText: 'Delete',
            isDangerous: true,
        });
        if (!ok) return;
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

    useEffect(() => {
        const onKeyDown = (e) => {
            const target = e.target;
            const typing =
                target instanceof HTMLElement &&
                (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

            // These two shortcuts are modifier-based and target the chapter the
            // user is writing, so unlike every other handler in the app they must
            // NOT bail when the caret is in a field. The guard was unconditional,
            // and the chapter editor IS a <textarea> — so `Ctrl+S` and
            // `Ctrl+Shift+C` were dead in the only place they are useful, while
            // the Keyboard Shortcuts modal (mounted globally from Layout) still
            // advertised them. `Ctrl+S` additionally fell through to the
            // browser's "Save page" dialog.
            //
            // Text inputs other than the chapter editor are still excluded, so a
            // search box or a rename field keeps its native behaviour.
            const isChapterEditor =
                target instanceof HTMLElement &&
                (target.tagName === 'TEXTAREA' || target.isContentEditable);

            if (typing && !isChapterEditor) return;

            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                e.preventDefault();
                handleSaveChapter();
            } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'c') {
                e.preventDefault();
                if (editorContent) {
                    // `copyToClipboard`, not `navigator.clipboard.writeText(...).then().catch()`:
                    // a bare promise chain does NOT contain a synchronous
                    // TypeError thrown by the dereference itself. This handler
                    // runs from a keydown listener, so the throw also had
                    // nowhere to surface — Ctrl+Shift+C did nothing at all on a
                    // LAN address, with no message.
                    copyToClipboard(editorContent).then((copied) => {
                        if (copied) {
                            toast.success('Chapter content copied to clipboard');
                        } else {
                            toast.error('Failed to copy content');
                        }
                    });
                }
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [handleSaveChapter, editorContent]);

    const handleIllustrate = useCallback(async () => {
        if (!activeStoryId || !activeChapterId || isIllustrating) return;
        
        let selectedText = '';
        if (textareaRef.current) {
            const start = textareaRef.current.selectionStart;
            const end = textareaRef.current.selectionEnd;
            if (start !== end) {
                selectedText = textareaRef.current.value.substring(start, end);
            }
        } else {
            selectedText = window.getSelection().toString();
        }
        
        if (selectedText) {
            setIllustratePrompt(selectedText);
        } else {
            setIllustratePrompt(lastIllustrationPrompt);
        }
        
        setShowIllustrateModal(true);
     
    }, [activeStoryId, activeChapterId, isIllustrating, lastIllustrationPrompt]);

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
            setLastIllustrationPrompt(illustratePrompt.trim());
            setIllustratePrompt('');
            toast('Generating illustration...', { icon: '🎨' });
        } catch {
            toast.error('Failed to start illustration');
            setIsIllustrating(false);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeStoryId, activeChapterId, illustratePrompt, illustrateChapter]);

    const handleBatchVariations = useCallback(() => {
        if (!lastIllustrationPrompt) return;
        sessionStorage.setItem('tnhcomfy_batch_prompt', lastIllustrationPrompt);
        navigate('/batch-generate');
    }, [lastIllustrationPrompt, navigate]);

    const handleStoryTitleUpdate = async (e) => {
        const newTitle = e.target.value;
        // The early return on `!newTitle.trim()` meant clearing the field and
        // blurring did nothing server-side, while the input kept displaying
        // empty — so the UI and the database silently diverged. The backend
        // accepts an empty title (there is no min-length on it), so the only
        // question is whether the story exists.
        if (!activeStoryId) return;
        if (newTitle === (activeStory?.title ?? '')) return;
        try {
            await updateStory.mutateAsync({ id: activeStoryId, title: newTitle.trim() });
        } catch {
            toast.error('Failed to save story title');
        }
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
                    onImportParse={() => setShowParseModal(true)}
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
                        onReorder={handleReorderChapters}
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
                                worlds={worlds}
                                worldId={newStoryWorldId}
                                onWorldChange={setNewStoryWorldId}
                                onConfirm={handleCreateStoryFromModal}
                                onClose={() => { setShowCreateModal(false); setNewStoryTitle(''); setNewStoryWorldId(''); }}
                            />
                        )}
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
                                    wordCountGoal={activeStory?.word_count_goal || null}
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
                                                onReorder={handleReorderBeats}
                                                onUpdateBeat={handleEditBeat}
                                                onDeleteBeat={handleDeleteBeat}
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
                                            aiDirective={aiDirective}
                                            onAiDirectiveChange={setAiDirective}
                                            canRetryLast={activeChapter?.beats?.length > 0 && activeChapter.beats[activeChapter.beats.length - 1]?.role === 'narrator'}
                                            onRetryLast={handleRetryLast}
                                            onOpenRevisions={() => setRevisionsOpen(true)}
                                            onAiAction={handleOpenStoryAction}
                                            isIllustrating={isIllustrating}
                                            onIllustrate={handleIllustrate}
                                            beatInput={beatInput}
                                            onBeatInputChange={setBeatInput}
                                            onAddBeat={handleAddBeat}
                                            beatRole={beatRole}
                                            onBeatRoleChange={setBeatRole}
                                            onExport={handleExportStory}
                                            onPublish={handlePublishStory}
                                            isPublished={activeStory?.is_published}
                                            onNarrate={handleNarrateChapter}
                                            activeChapterId={activeChapter?.id}
                                            onBatchVariations={handleBatchVariations}
                                            hasIllustration={!!lastIllustrationPrompt}
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
                            locations={locations}
                            worlds={worlds}
                            scenarios={scenarios}
                            queryErrors={queryErrors}
                            storyImages={storyImages}
                            chapters={chapters}
                            llmModels={llmModels}
                            defaultLlmConfig={defaultLlmConfig}
                            onClose={() => { setMobileTab('write'); setIsPanelOpen(false); }}
                            onShowGallery={() => setShowGallery(true)}
                            onUpdateStory={(updates) => { if (activeStoryId) updateStory.mutate({ id: activeStoryId, ...updates }); }}
                            onEditCharacter={setEditingCharacter}
                            onEditLorebook={(lb) => { setEditingLorebook(lb); setShowLorebookModal(true); }}
                            onEditLocation={(loc) => { setEditingLocation(loc); setShowLocationModal(true); }}
                            onOpenRevisions={activeChapterId ? () => setRevisionsOpen(true) : undefined}
                            onSnapshotChapter={activeChapterId ? handleSaveRevision : undefined}
                            isSnapshotting={createRevision.isPending}
                        />
                    </motion.div>
                )}
            </AnimatePresence>

            <LorebookModal
                isOpen={showLorebookModal}
                onClose={() => { setEditingLorebook(null); setShowLorebookModal(false); }}
                lorebook={editingLorebook}
            />

            {/* Must live OUTSIDE the `!activeStoryId` branch: setEditingCharacter
                is only ever called from StoryContextPanel, which renders only
                when a story is active. Inside the branch "Edit Character" from
                the context panel did nothing at all. */}
            {editingCharacter && (
                <CharacterModal
                    isOpen={true}
                    onClose={() => setEditingCharacter(null)}
                    character={editingCharacter}
                    onSave={handleSaveCharacter}
                />
            )}

            <LocationModal
                isOpen={showLocationModal}
                onClose={() => { setEditingLocation(null); setShowLocationModal(false); }}
                location={editingLocation}
            />

            <IllustrateModal
                isOpen={showIllustrateModal}
                prompt={illustratePrompt}
                onPromptChange={setIllustratePrompt}
                onConfirm={handleConfirmIllustrate}
                onClose={() => { setShowIllustrateModal(false); setIllustratePrompt(''); }}
            />

            <StoryActionModal
                isOpen={!!storyAction}
                action={storyAction?.action}
                selectionText={storyAction?.selectionText || ''}
                directive={storyAction?.directive || ''}
                onDirectiveChange={(v) => setStoryAction(sa => sa ? { ...sa, directive: v } : sa)}
                isRunning={isActionRunning}
                result={actionResult}
                onConfirm={handleConfirmStoryAction}
                onApply={handleApplyStoryAction}
                onClose={handleCloseStoryAction}
            />

            <ChapterRevisionsModal
                isOpen={revisionsOpen}
                chapterTitle={activeChapter?.title || 'Untitled chapter'}
                revisions={chapterRevisions.data || []}
                isLoading={chapterRevisions.isLoading}
                isRestoring={restoreRevision.isPending}
                onRestore={handleRestoreRevision}
                onSnapshot={handleSaveRevision}
                onClose={() => setRevisionsOpen(false)}
            />

            <StoryGalleryModal
                isOpen={showGallery}
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
        {/* Rendered outside the activeStoryId ternary, not inside the empty-state
            branch. The sidebar's "Import & Parse Story" button is rendered
            unconditionally and always dispatches open-parse-story, but the only
            copy of this modal used to live in the `!activeStoryId` branch — and a
            story is auto-selected as soon as one exists, so the button set
            showParseModal(true) with nothing mounted to react to it. Import was
            reachable only from the state where you have no use for it. */}
        <ParseStoryModal
            isOpen={showParseModal}
            onClose={() => setShowParseModal(false)}
            onComplete={handleParseStoryComplete}
        />
        </motion.div>
    );
}
