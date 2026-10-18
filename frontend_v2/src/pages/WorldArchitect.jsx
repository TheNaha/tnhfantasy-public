import clsx from 'clsx';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    Sparkles, Upload, FileText, Globe2, Users, MapPin, BookOpen, Shield, Clock,
    Check, Plus, ArrowRight, Loader2, Eye, Wand2, Layers, Compass, Shirt, User,
    Lock, Unlock, Tag, Heart, Trash2, RotateCcw, MessageSquare
} from 'lucide-react';
import {
    useCharacters,
    useWorlds,
    useLocations,
    useAnalyzeCardOnboarding,
    useAnalyzeExistingCharacterOnboarding,
    useAnalyzeDocumentOnboarding,
    useCrossoverPreview,
    useCommitWorldBlueprint,
    useRunWorldTick,
    useExtractScenarios,
    useExtractVisualTags,
    useExtractStatekeeper,
    useExtractWorldLore,
    useEnrichField,
    useIngestStoryChained,
} from '../hooks/useWorldVault';

import CardSourceInspector from '../components/world_architect/CardSourceInspector';
import ScenariosMappingTab from '../components/world_architect/ScenariosMappingTab';
import StatekeeperTurn0Tab from '../components/world_architect/StatekeeperTurn0Tab';

const ARCHETYPE_CARDS = [
    {
        id: 'rift_portal',
        label: 'Dimensional Rift / Portal',
        summary: 'A spatial anomaly pulls the traveler(s) directly into the destination world with their original gear and powers intact.',
    },
    {
        id: 'reincarnation',
        label: 'Isekai Reincarnation / Awakening',
        summary: 'The traveler awakens in the destination world with full memories of their origin world, adapting their signature skills to local laws.',
    },
    {
        id: 'world_collision',
        label: 'Convergence / World Collision',
        summary: 'Landmarks from both worlds fuse together in a cataclysmic convergence, forcing residents and travelers to coexist.',
    },
    {
        id: 'summoned_hero',
        label: 'Arcane / Tech Summoning',
        summary: 'A ritual or quantum beacon in the destination world deliberately summons the traveler(s) to resolve an impending crisis.',
    },
];

export default function WorldArchitect() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const initialTab = searchParams.get('tab') || 'card';
    const preselectedCharId = searchParams.get('characterId') || '';

    const [activeTab, setActiveTab] = useState(initialTab);
    const { data: characters = [] } = useCharacters();
    const { data: worlds = [] } = useWorlds();
    const { data: locations = [] } = useLocations();

    const analyzeCard = useAnalyzeCardOnboarding();
    const analyzeExistingChar = useAnalyzeExistingCharacterOnboarding();
    const analyzeDocument = useAnalyzeDocumentOnboarding();
    const crossoverPreviewMut = useCrossoverPreview();
    const commitBlueprintMut = useCommitWorldBlueprint();
    const runWorldTickMut = useRunWorldTick();

    const extractScenariosMut = useExtractScenarios();
    const extractVisualTagsMut = useExtractVisualTags();
    const extractStatekeeperMut = useExtractStatekeeper();
    const extractWorldLoreMut = useExtractWorldLore();
    const enrichFieldMut = useEnrichField();
    const ingestStoryChainedMut = useIngestStoryChained();

    // Card Onboarding State
    const [cardFile, setCardFile] = useState(null);
    const [selectedExistingCharId, setSelectedExistingCharId] = useState(preselectedCharId);
    const [useVision, setUseVision] = useState(true);

    // Document / Story Ingestion State
    const [docFile, setDocFile] = useState(null);
    const [storyTitle, setStoryTitle] = useState('');
    const [storyRawText, setStoryRawText] = useState('');
    const [isChainedIngest, setIsChainedIngest] = useState(false);

    // Shared Editable Blueprint State
    const [blueprint, setBlueprint] = useState(null);
    const [launchChat, setLaunchChat] = useState(true);
    const [launchStory, setLaunchStory] = useState(false);
    const [errorMsg, setErrorMsg] = useState('');

    // Right Pane Tab Navigation
    const [activeIntegrationTab, setActiveIntegrationTab] = useState('cast');

    // Director & Statekeeper Locked Fields
    const [lockedFields, setLockedFields] = useState(['character_mood', 'scene_tension']);

    // Multi-tier Generator States
    const [isAutoArchitecting, setIsAutoArchitecting] = useState(false);
    const [autoArchitectStep, setAutoArchitectStep] = useState('');
    const [isRefiningScenarios, setIsRefiningScenarios] = useState(false);
    const [isGeneratingVisuals, setIsGeneratingVisuals] = useState(false);
    const [isSynthesizingTurn0, setIsSynthesizingTurn0] = useState(false);
    const [isGeneratingWorldLore, setIsGeneratingWorldLore] = useState(false);
    const [enrichingFieldKey, setEnrichingFieldKey] = useState(null);

    // Crossover Studio State
    const [travelerIds, setTravelerIds] = useState([]);
    const [targetWorldId, setTargetWorldId] = useState('');
    const [targetLocationId, setTargetLocationId] = useState('');
    const [residentIds, setResidentIds] = useState([]);
    const [archetype, setArchetype] = useState('rift_portal');
    const [customPremise, setCustomPremise] = useState('');
    const [crossoverPreview, setCrossoverPreview] = useState(null);
    const [worldTickResult, setWorldTickResult] = useState(null);

    const handleToggleLock = (field) => {
        setLockedFields((prev) => {
            const next = prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field];
            if (blueprint?.initial_state_snapshot) {
                setBlueprint((bp) => ({
                    ...bp,
                    initial_state_snapshot: {
                        ...bp.initial_state_snapshot,
                        locked_fields: next,
                    },
                }));
            }
            return next;
        });
    };

    const handleAnalyzeCard = async (e) => {
        e.preventDefault();
        setErrorMsg('');
        try {
            if (cardFile) {
                const res = await analyzeCard.mutateAsync({ file: cardFile, useVision });
                setBlueprint(res);
                setLaunchChat(true);
                setLaunchStory(false);
            } else if (selectedExistingCharId) {
                const res = await analyzeExistingChar.mutateAsync({
                    characterId: selectedExistingCharId,
                    useVision,
                });
                setBlueprint(res);
                setLaunchChat(true);
                setLaunchStory(false);
            } else {
                setErrorMsg('Upload a SillyTavern card (.png/.json/.charx) or choose an existing character.');
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to analyze character card.');
        }
    };

    const handleAnalyzeDocument = async (e) => {
        e.preventDefault();
        setErrorMsg('');
        if (!docFile && !storyRawText.trim()) {
            setErrorMsg('Upload a .pdf, .txt, or .md file, or paste story prose below.');
            return;
        }

        const isLongText = (storyRawText.trim().split(/\s+/).length > 2500);

        try {
            if (isLongText || isChainedIngest) {
                const res = await ingestStoryChainedMut.mutateAsync({
                    raw_text: storyRawText.trim(),
                    title: storyTitle || null,
                    chunk_size_words: 3500,
                    overlap_words: 200,
                });
                setBlueprint(res);
                setLaunchChat(true);
                setLaunchStory(true);
            } else {
                const res = await analyzeDocument.mutateAsync({
                    file: docFile,
                    rawText: storyRawText,
                    title: storyTitle,
                });
                setBlueprint(res);
                setLaunchChat(true);
                setLaunchStory(true);
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to extract world blueprint from story.');
        }
    };

    const handleAutoArchitectAll = async () => {
        if (!blueprint) return;
        setIsAutoArchitecting(true);
        setErrorMsg('');
        try {
            const char = blueprint.characters?.[0] || {};

            // Step 1: Visual Tags & Wardrobe
            setAutoArchitectStep('Step 1/4: Synthesizing visual tags & wardrobe presets...');
            const visRes = await extractVisualTagsMut.mutateAsync({
                char_name: char.name || 'Character',
                description: char.description || '',
                personality: char.personality || '',
                avatar_base64: char.avatar_base64 || blueprint.source_card?.avatar_base64 || null,
                existing_tags: char.visual_tags || [],
                use_vision: useVision,
            });

            // Step 2: Director Turn-0 Statekeeper (strictly respecting lockedFields)
            setAutoArchitectStep('Step 2/4: Synthesizing Turn-0 Statekeeper (preserving locked fields)...');
            const stateRes = await extractStatekeeperMut.mutateAsync({
                char_name: char.name || 'Character',
                description: char.description || '',
                personality: char.personality || '',
                scenario_text: char.scenario || '',
                first_mes: char.first_mes || '',
                default_location: char.default_location || blueprint.locations?.[0]?.name,
                default_time: char.default_time,
                locked_fields: lockedFields,
                current_state: blueprint.initial_state_snapshot || {},
            });

            // Step 3: World & Locations Lore
            setAutoArchitectStep('Step 3/4: Generating World Setting, Locations & Codex...');
            const worldRes = await extractWorldLoreMut.mutateAsync({
                char_name: char.name || 'Character',
                description: char.description || '',
                scenario_text: char.scenario || '',
                first_mes: char.first_mes || '',
                character_book: blueprint.source_card?.character_book || null,
                existing_locations: blueprint.locations || [],
                locked_fields: lockedFields,
            });

            // Step 4: Scenarios & Alternate Greetings
            setAutoArchitectStep('Step 4/4: Refining Scenarios & Alternate Greetings...');
            const scenRes = await extractScenariosMut.mutateAsync({
                char_name: char.name || 'Character',
                scenario_text: char.scenario || '',
                first_mes: char.first_mes || '',
                alternate_greetings: blueprint.source_card?.alternate_greetings || [],
                default_location: worldRes.locations?.[0]?.name || char.default_location || 'Starting Area',
                default_time: char.default_time || 'Evening',
                use_llm: true,
            });

            // Apply all synthesized updates to blueprint
            setBlueprint((prev) => {
                const nextChars = [...(prev.characters || [])];
                if (nextChars.length > 0) {
                    nextChars[0] = {
                        ...nextChars[0],
                        visual_tags: visRes.visual_tags || nextChars[0].visual_tags,
                        wardrobe: visRes.wardrobe_presets || nextChars[0].wardrobe,
                    };
                }
                return {
                    ...prev,
                    characters: nextChars,
                    world: {
                        ...prev.world,
                        name: worldRes.world_name || prev.world?.name,
                        description: worldRes.world_description || prev.world?.description,
                    },
                    locations: worldRes.locations || prev.locations,
                    lorebook: worldRes.lorebook || prev.lorebook,
                    scenarios: scenRes.scenarios || prev.scenarios,
                    initial_state_snapshot: {
                        ...prev.initial_state_snapshot,
                        ...(stateRes.initial_state_snapshot || {}),
                    },
                };
            });

            setAutoArchitectStep('✨ Auto-Architect complete! All sections updated.');
            setTimeout(() => setAutoArchitectStep(''), 3000);
        } catch (err) {
            setErrorMsg(err?.message || 'Auto-Architect pipeline failed.');
            setAutoArchitectStep('');
        } finally {
            setIsAutoArchitecting(false);
        }
    };

    const handleRefineScenarios = async () => {
        if (!blueprint) return;
        setIsRefiningScenarios(true);
        try {
            const char = blueprint.characters?.[0] || {};
            const res = await extractScenariosMut.mutateAsync({
                char_name: char.name || 'Character',
                scenario_text: char.scenario || '',
                first_mes: char.first_mes || '',
                alternate_greetings: blueprint.source_card?.alternate_greetings || [],
                default_location: char.default_location || 'Starting Area',
                default_time: char.default_time || 'Evening',
                use_llm: true,
            });
            if (res.scenarios) {
                setBlueprint((prev) => ({
                    ...prev,
                    scenarios: res.scenarios,
                }));
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to refine scenarios.');
        } finally {
            setIsRefiningScenarios(false);
        }
    };

    const handleGenerateVisualTags = async () => {
        if (!blueprint) return;
        setIsGeneratingVisuals(true);
        try {
            const char = blueprint.characters?.[0] || {};
            const res = await extractVisualTagsMut.mutateAsync({
                char_name: char.name || 'Character',
                description: char.description || '',
                personality: char.personality || '',
                avatar_base64: char.avatar_base64 || blueprint.source_card?.avatar_base64 || null,
                existing_tags: char.visual_tags || [],
                use_vision: useVision,
            });
            if (res.visual_tags) {
                setBlueprint((prev) => {
                    const nextChars = [...prev.characters];
                    nextChars[0] = {
                        ...nextChars[0],
                        visual_tags: res.visual_tags,
                        wardrobe: res.wardrobe_presets || nextChars[0].wardrobe,
                    };
                    return { ...prev, characters: nextChars };
                });
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to generate visual tags.');
        } finally {
            setIsGeneratingVisuals(false);
        }
    };

    const handleSynthesizeTurn0 = async () => {
        if (!blueprint) return;
        setIsSynthesizingTurn0(true);
        try {
            const char = blueprint.characters?.[0] || {};
            const res = await extractStatekeeperMut.mutateAsync({
                char_name: char.name || 'Character',
                description: char.description || '',
                personality: char.personality || '',
                scenario_text: char.scenario || '',
                first_mes: char.first_mes || '',
                default_location: char.default_location,
                default_time: char.default_time,
                locked_fields: lockedFields,
                current_state: blueprint.initial_state_snapshot || {},
            });
            if (res.initial_state_snapshot) {
                setBlueprint((prev) => ({
                    ...prev,
                    initial_state_snapshot: res.initial_state_snapshot,
                }));
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to synthesize Turn-0 state.');
        } finally {
            setIsSynthesizingTurn0(false);
        }
    };

    const handleGenerateWorldLore = async () => {
        if (!blueprint) return;
        setIsGeneratingWorldLore(true);
        try {
            const char = blueprint.characters?.[0] || {};
            const res = await extractWorldLoreMut.mutateAsync({
                char_name: char.name || 'Character',
                description: char.description || '',
                scenario_text: char.scenario || '',
                first_mes: char.first_mes || '',
                character_book: blueprint.source_card?.character_book || null,
                existing_locations: blueprint.locations || [],
                locked_fields: lockedFields,
            });
            setBlueprint((prev) => ({
                ...prev,
                world: {
                    ...prev.world,
                    name: res.world_name || prev.world?.name,
                    description: res.world_description || prev.world?.description,
                },
                locations: res.locations || prev.locations,
                lorebook: res.lorebook || prev.lorebook,
            }));
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to generate world lore.');
        } finally {
            setIsGeneratingWorldLore(false);
        }
    };

    const handleEnrichField = async (fieldKey, currentValue, instruction) => {
        if (!currentValue) return;
        setEnrichingFieldKey(fieldKey);
        try {
            const char = blueprint.characters?.[0] || {};
            const res = await enrichFieldMut.mutateAsync({
                field_name: fieldKey,
                current_value: currentValue,
                char_name: char.name || '',
                context: char.scenario || blueprint.world?.description || '',
                instruction: instruction || 'Enrich with vivid sensory details and atmospheric prose.',
            });
            if (res.enriched_value) {
                if (fieldKey === 'description' || fieldKey === 'personality' || fieldKey === 'scenario') {
                    setBlueprint((prev) => {
                        const nextChars = [...prev.characters];
                        nextChars[0] = { ...nextChars[0], [fieldKey]: res.enriched_value };
                        return { ...prev, characters: nextChars };
                    });
                } else if (fieldKey === 'world_description') {
                    setBlueprint((prev) => ({
                        ...prev,
                        world: { ...prev.world, description: res.enriched_value },
                    }));
                }
            }
        } catch (err) {
            setErrorMsg(err?.message || `Failed to enrich ${fieldKey}.`);
        } finally {
            setEnrichingFieldKey(null);
        }
    };

    const handleCommitBlueprint = async () => {
        if (!blueprint) return;
        setErrorMsg('');
        try {
            const res = await commitBlueprintMut.mutateAsync({
                ...blueprint,
                launch_chat: launchChat,
                launch_story: launchStory,
            });
            if (res.chat_id) {
                navigate(`/chat/${res.chat_id}`);
            } else if (res.story_id) {
                navigate(`/story/${res.story_id}`);
            } else if (res.world_id) {
                navigate(`/worlds/${res.world_id}`);
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to commit World Blueprint.');
        }
    };

    const handleToggleTraveler = (id) => {
        setTravelerIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    };

    const handleToggleResident = (id) => {
        setResidentIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    };

    const handlePreviewCrossover = async (commitImmediately = false) => {
        if (travelerIds.length === 0) {
            setErrorMsg('Select at least one Traveler Character.');
            return;
        }
        if (!targetWorldId) {
            setErrorMsg('Select a Destination World.');
            return;
        }
        setErrorMsg('');
        try {
            const res = await crossoverPreviewMut.mutateAsync({
                traveler_character_ids: travelerIds,
                target_world_id: targetWorldId,
                archetype,
                target_location_id: targetLocationId || null,
                resident_character_ids: residentIds,
                custom_premise: customPremise || null,
                commit_immediately: commitImmediately,
            });
            setCrossoverPreview(res);
            if (commitImmediately && res.launched_chat_id) {
                navigate(`/chats?chatId=${res.launched_chat_id}`);
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to generate crossover scenario.');
        }
    };

    const targetWorldLocations = locations.filter((l) => l.world_id === targetWorldId);
    const isAnalyzing = analyzeCard.isPending || analyzeExistingChar.isPending || analyzeDocument.isPending || ingestStoryChainedMut.isPending;

    return (
        <div className="space-y-6 pb-20">
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                    <h1 className="text-xl font-extrabold text-white flex items-center gap-2">
                        <Compass className="text-emerald-400" size={24} />
                        World Architect &amp; SillyTavern Ingestion Studio
                    </h1>
                    <p className="text-xs text-gray-400 mt-1">
                        Dual-pane ingestion manager: inspect raw cards on the left, auto-architect and map scenarios, locations, lorebooks, and Turn-0 state on the right.
                    </p>
                </div>

                {blueprint && (
                    <button
                        type="button"
                        onClick={() => {
                            setBlueprint(null);
                            setCardFile(null);
                        }}
                        className="px-3 py-1.5 rounded-xl bg-gray-800 hover:bg-gray-700 border border-white/10 text-gray-300 text-xs font-semibold flex items-center gap-1.5 transition-all"
                    >
                        <RotateCcw size={13} />
                        <span>Load Another Card</span>
                    </button>
                )}
            </div>

            {/* Ingestion Mode Navigation */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {[
                    {
                        id: 'card',
                        label: 'SillyTavern Card -> World',
                        sub: 'Character Card (.png / .json / .charx)',
                        icon: Sparkles,
                    },
                    {
                        id: 'document',
                        label: 'Story Document -> World',
                        sub: 'Long Fiction / PDF / Chained Ingest',
                        icon: BookOpen,
                    },
                    {
                        id: 'crossover',
                        label: 'Multiverse Crossover Studio',
                        sub: 'Isekai / Dimensional Rift / Portal',
                        icon: Globe2,
                    },
                ].map((tab) => {
                    const Icon = tab.icon;
                    const active = activeTab === tab.id;
                    return (
                        <button
                            key={tab.id}
                            type="button"
                            onClick={() => {
                                setActiveTab(tab.id);
                                setErrorMsg('');
                            }}
                            className={clsx(
                                'p-3.5 rounded-xl border text-left transition-all flex items-start gap-3',
                                active
                                    ? 'bg-emerald-500/15 border-emerald-500/40 text-white shadow-lg'
                                    : 'bg-gray-900/60 border-white/10 text-gray-400 hover:text-gray-200 hover:border-white/20'
                            )}
                        >
                            <Icon size={18} className={active ? 'text-emerald-400 mt-0.5' : 'text-gray-500 mt-0.5'} />
                            <div>
                                <div className="text-sm font-bold">{tab.label}</div>
                                <div className="text-xs text-gray-400 mt-0.5">{tab.sub}</div>
                            </div>
                        </button>
                    );
                })}
            </div>

            {errorMsg && (
                <div className="p-3.5 rounded-xl bg-red-500/15 border border-red-500/30 text-red-200 text-xs font-medium flex items-center gap-2">
                    <span>{errorMsg}</span>
                </div>
            )}

            {/* TAB 1: CARD UPLOAD FORM (SHOWN WHEN NO BLUEPRINT LOADED) */}
            {activeTab === 'card' && !blueprint && (
                <form onSubmit={handleAnalyzeCard} className="glass-panel rounded-2xl p-5 border border-white/10 space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                                Upload SillyTavern Card (.png, .json, .charx)
                            </label>
                            <input
                                type="file"
                                accept=".png,.json,.charx"
                                onChange={(e) => {
                                    setCardFile(e.target.files?.[0] || null);
                                    if (e.target.files?.[0]) setSelectedExistingCharId('');
                                }}
                                className="w-full text-xs text-gray-300 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-emerald-500/20 file:text-emerald-300 hover:file:bg-emerald-500/30 bg-gray-900/70 border border-white/10 rounded-xl p-2"
                            />
                        </div>

                        <div className="space-y-2">
                            <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                                Or Expand an Existing Character Into a Full World
                            </label>
                            <select
                                value={selectedExistingCharId}
                                onChange={(e) => {
                                    setSelectedExistingCharId(e.target.value);
                                    if (e.target.value) setCardFile(null);
                                }}
                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2.5 text-xs text-gray-200 focus:outline-none focus:border-emerald-500/50"
                            >
                                <option value="">— Select existing character —</option>
                                {characters.map((c) => (
                                    <option key={c.id} value={c.id}>
                                        {c.name}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-white/5">
                        <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
                            <input
                                type="checkbox"
                                checked={useVision}
                                onChange={(e) => setUseVision(e.target.checked)}
                                className="accent-emerald-500"
                            />
                            <Eye size={14} className="text-pink-400" />
                            <span>
                                Use <b>Vision LLM</b> on embedded portrait to extract visual tags, wardrobe presets &amp; backdrop
                            </span>
                        </label>

                        <button
                            type="submit"
                            disabled={isAnalyzing}
                            className="px-5 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center gap-2 shadow-lg disabled:opacity-50"
                        >
                            {isAnalyzing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                            Analyze &amp; Launch Dual-Pane Ingestion Manager
                        </button>
                    </div>
                </form>
            )}

            {/* TAB 2: DOCUMENT / STORY FORM (SHOWN WHEN NO BLUEPRINT LOADED) */}
            {activeTab === 'document' && !blueprint && (
                <form onSubmit={handleAnalyzeDocument} className="glass-panel rounded-2xl p-5 border border-white/10 space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-2">
                            <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                                Upload Story File (.pdf, .txt, .md)
                            </label>
                            <input
                                type="file"
                                accept=".pdf,.txt,.md,.markdown"
                                onChange={(e) => setDocFile(e.target.files?.[0] || null)}
                                className="w-full text-xs text-gray-300 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-purple-500/20 file:text-purple-300 hover:file:bg-purple-500/30 bg-gray-900/70 border border-white/10 rounded-xl p-2"
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                                World / Story Title (Optional)
                            </label>
                            <input
                                type="text"
                                value={storyTitle}
                                onChange={(e) => setStoryTitle(e.target.value)}
                                placeholder="e.g. Chronicles of the Obsidian Watchtower"
                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2 text-xs text-gray-200 focus:outline-none focus:border-purple-500/50"
                            />
                        </div>
                    </div>

                    <div className="space-y-2">
                        <div className="flex items-center justify-between">
                            <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                                Or Paste Story Prose / Lore Chapter Directly
                            </label>
                            <label className="flex items-center gap-1.5 text-2xs text-purple-300 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={isChainedIngest}
                                    onChange={(e) => setIsChainedIngest(e.target.checked)}
                                    className="accent-purple-500"
                                />
                                <span>Chained Long Ingestion (for 50k+ words)</span>
                            </label>
                        </div>
                        <textarea
                            rows={6}
                            value={storyRawText}
                            onChange={(e) => setStoryRawText(e.target.value)}
                            placeholder="Paste a chapter, novel manuscript, or massive story text here. The sliding-window chained engine will accumulate entities across chunks without context blowout..."
                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl p-3 text-xs text-gray-200 focus:outline-none focus:border-purple-500/50"
                        />
                    </div>

                    <div className="flex justify-end">
                        <button
                            type="submit"
                            disabled={isAnalyzing}
                            className="px-5 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold flex items-center gap-2 shadow-lg disabled:opacity-50"
                        >
                            {isAnalyzing ? <Loader2 size={14} className="animate-spin" /> : <BookOpen size={14} />}
                            Extract Playable World &amp; Cast
                        </button>
                    </div>
                </form>
            )}

            {/* DUAL-PANE SILLYTAVERN INGESTION MANAGER & WORLD INTEGRATOR */}
            {(activeTab === 'card' || activeTab === 'document') && blueprint && (
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
                    {/* LEFT PANE: SOURCE CARD INSPECTOR */}
                    <div className="lg:col-span-5 sticky top-4 max-h-[calc(100vh-2.5rem)]">
                        <CardSourceInspector
                            sourceCard={blueprint.source_card || {
                                name: blueprint.characters?.[0]?.name,
                                description: blueprint.characters?.[0]?.description,
                                personality: blueprint.characters?.[0]?.personality,
                                scenario: blueprint.characters?.[0]?.scenario,
                                first_mes: blueprint.characters?.[0]?.first_mes,
                                alternate_greetings: blueprint.characters?.[0]?.alternate_greetings || [],
                                avatar_base64: blueprint.characters?.[0]?.avatar_base64,
                            }}
                            onCopyField={(_key) => {
                                // optional notification or clipboard sync
                            }}
                        />
                    </div>

                    {/* RIGHT PANE: TARGET WORLD VAULT INTEGRATION STUDIO */}
                    <div className="lg:col-span-7 space-y-4">
                        {/* Top Master Toolbar: [⚡ Auto-Architect All] One-Button Pipeline */}
                        <div className="glass-panel rounded-2xl p-4 border border-emerald-500/30 bg-gradient-to-r from-emerald-950/30 to-purple-950/20 shadow-xl space-y-3">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <div>
                                    <div className="flex items-center gap-2">
                                        <h2 className="text-sm font-extrabold text-white">Target World Vault Integration</h2>
                                        <span className="px-2 py-0.5 rounded-full text-3xs font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                                            Live Ingestion
                                        </span>
                                    </div>
                                    <p className="text-2xs text-gray-400 mt-0.5">
                                        Deterministic auto-mapping loaded. Refine sections individually or run Master Auto-Architect.
                                    </p>
                                </div>

                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={handleAutoArchitectAll}
                                        disabled={isAutoArchitecting}
                                        className="px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-400 hover:from-emerald-400 hover:to-teal-300 text-gray-950 text-xs font-extrabold flex items-center gap-2 shadow-lg transition-all transform hover:scale-[1.02] disabled:opacity-50"
                                        title="Execute sequential 4-stage LLM generation for Visuals, Turn-0 State, World Lore, and Scenarios while respecting locked fields"
                                    >
                                        {isAutoArchitecting ? <Loader2 size={14} className="animate-spin text-gray-950" /> : <Sparkles size={14} />}
                                        <span>{isAutoArchitecting ? 'Auto-Architecting...' : '⚡ Auto-Architect All'}</span>
                                    </button>
                                </div>
                            </div>

                            {/* Auto-Architect Step Live Progress Indicator */}
                            {autoArchitectStep && (
                                <div className="px-3 py-1.5 rounded-xl bg-black/40 border border-emerald-500/30 text-2xs font-mono text-emerald-300 flex items-center gap-2">
                                    {isAutoArchitecting && <Loader2 size={12} className="animate-spin text-emerald-400" />}
                                    <span>{autoArchitectStep}</span>
                                </div>
                            )}

                            {/* Telemetry Chips */}
                            <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-white/5 text-2xs text-gray-400">
                                <span>Cast: <b className="text-white">{blueprint.characters?.length || 0}</b></span>
                                <span>•</span>
                                <span>Scenarios: <b className="text-white">{blueprint.scenarios?.length || 0}</b></span>
                                <span>•</span>
                                <span>Locations: <b className="text-white">{blueprint.locations?.length || 0}</b></span>
                                <span>•</span>
                                <span>Lore: <b className="text-white">{blueprint.lorebook?.entries?.length || 0}</b></span>
                                {lockedFields.length > 0 && (
                                    <>
                                        <span>•</span>
                                        <span className="text-amber-400 font-semibold flex items-center gap-1">
                                            <Lock size={10} /> {lockedFields.length} fields locked
                                        </span>
                                    </>
                                )}
                            </div>
                        </div>

                        {/* Right Pane Tab Navigation */}
                        <div className="flex flex-wrap gap-1 p-1 rounded-xl bg-gray-900/80 border border-white/10 text-xs">
                            {[
                                { id: 'cast', label: 'Cast & Persona', icon: Users },
                                { id: 'scenarios', label: `Scenarios (${blueprint.scenarios?.length || 0})`, icon: MessageSquare },
                                { id: 'statekeeper', label: 'Director Turn-0', icon: Shield, badge: lockedFields.length > 0 ? `${lockedFields.length} 🔒` : null },
                                { id: 'world', label: 'World & Locations', icon: Globe2 },
                                { id: 'lorebook', label: `Codex (${blueprint.lorebook?.entries?.length || 0})`, icon: BookOpen },
                                ...(blueprint.story_chapters?.length ? [{ id: 'story', label: `Story Sandbox (${blueprint.story_chapters.length} Ch.)`, icon: BookOpen }] : []),
                            ].map((tab) => {
                                const Icon = tab.icon;
                                const active = activeIntegrationTab === tab.id;
                                return (
                                    <button
                                        key={tab.id}
                                        type="button"
                                        onClick={() => setActiveIntegrationTab(tab.id)}
                                        className={clsx(
                                            'px-3 py-1.5 rounded-lg font-semibold flex items-center gap-1.5 transition-all text-2xs sm:text-xs',
                                            active
                                                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-sm'
                                                : 'text-gray-400 hover:text-gray-200 hover:bg-white/5'
                                        )}
                                    >
                                        <Icon size={13} />
                                        <span>{tab.label}</span>
                                        {tab.badge && (
                                            <span className="px-1 py-0.2 rounded text-3xs font-mono font-bold bg-amber-500/20 text-amber-300">
                                                {tab.badge}
                                            </span>
                                        )}
                                    </button>
                                );
                            })}
                        </div>

                        {/* TAB 1: CAST & PERSONA */}
                        {activeIntegrationTab === 'cast' && (
                            <div className="space-y-4">
                                {(blueprint.characters || []).map((char, idx) => (
                                    <div key={idx} className="glass-panel rounded-2xl p-5 border border-white/10 space-y-4 text-xs">
                                        <div className="flex items-center justify-between gap-3">
                                            <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                                <User size={16} className="text-purple-400" />
                                                Character #{idx + 1}: {char.name}
                                            </h3>

                                            <button
                                                type="button"
                                                onClick={handleGenerateVisualTags}
                                                disabled={isGeneratingVisuals}
                                                className="px-3 py-1 rounded-xl bg-purple-500/20 hover:bg-purple-500/30 border border-purple-500/30 text-purple-200 text-2xs font-semibold flex items-center gap-1.5"
                                            >
                                                <Sparkles size={12} className={isGeneratingVisuals ? 'animate-spin' : ''} />
                                                <span>{isGeneratingVisuals ? 'Generating Tags...' : '✨ Generate Tags & Wardrobe'}</span>
                                            </button>
                                        </div>

                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                                            <div className="space-y-1">
                                                <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                    Character Name
                                                </label>
                                                <input
                                                    type="text"
                                                    value={char.name || ''}
                                                    onChange={(e) => {
                                                        const next = [...blueprint.characters];
                                                        next[idx] = { ...char, name: e.target.value };
                                                        setBlueprint((prev) => ({ ...prev, characters: next }));
                                                    }}
                                                    className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white"
                                                />
                                            </div>

                                            <div className="grid grid-cols-2 gap-2">
                                                <div className="space-y-1">
                                                    <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                        Default Location
                                                    </label>
                                                    <input
                                                        type="text"
                                                        value={char.default_location || ''}
                                                        onChange={(e) => {
                                                            const next = [...blueprint.characters];
                                                            next[idx] = { ...char, default_location: e.target.value };
                                                            setBlueprint((prev) => ({ ...prev, characters: next }));
                                                        }}
                                                        className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-200"
                                                    />
                                                </div>
                                                <div className="space-y-1">
                                                    <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                        Default Time
                                                    </label>
                                                    <input
                                                        type="text"
                                                        value={char.default_time || ''}
                                                        onChange={(e) => {
                                                            const next = [...blueprint.characters];
                                                            next[idx] = { ...char, default_time: e.target.value };
                                                            setBlueprint((prev) => ({ ...prev, characters: next }));
                                                        }}
                                                        className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-200"
                                                    />
                                                </div>
                                            </div>
                                        </div>

                                        {/* Description + Enrich Button */}
                                        <div className="space-y-1">
                                            <div className="flex items-center justify-between">
                                                <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                    Description ({char.description?.length || 0} chars)
                                                </label>
                                                <button
                                                    type="button"
                                                    onClick={() => handleEnrichField('description', char.description)}
                                                    disabled={enrichingFieldKey === 'description'}
                                                    className="text-3xs text-purple-300 hover:text-purple-200 flex items-center gap-1 font-semibold"
                                                >
                                                    <Wand2 size={11} className={enrichingFieldKey === 'description' ? 'animate-spin' : ''} />
                                                    <span>{enrichingFieldKey === 'description' ? 'Enriching...' : '✨ Enrich Description'}</span>
                                                </button>
                                            </div>
                                            <textarea
                                                rows={3}
                                                value={char.description || ''}
                                                onChange={(e) => {
                                                    const next = [...blueprint.characters];
                                                    next[idx] = { ...char, description: e.target.value };
                                                    setBlueprint((prev) => ({ ...prev, characters: next }));
                                                }}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl p-2.5 text-xs text-gray-200"
                                            />
                                        </div>

                                        {/* Personality + Enrich Button */}
                                        <div className="space-y-1">
                                            <div className="flex items-center justify-between">
                                                <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                    Personality ({char.personality?.length || 0} chars)
                                                </label>
                                                <button
                                                    type="button"
                                                    onClick={() => handleEnrichField('personality', char.personality)}
                                                    disabled={enrichingFieldKey === 'personality'}
                                                    className="text-3xs text-purple-300 hover:text-purple-200 flex items-center gap-1 font-semibold"
                                                >
                                                    <Wand2 size={11} className={enrichingFieldKey === 'personality' ? 'animate-spin' : ''} />
                                                    <span>{enrichingFieldKey === 'personality' ? 'Enriching...' : '✨ Enrich Personality'}</span>
                                                </button>
                                            </div>
                                            <textarea
                                                rows={2}
                                                value={char.personality || ''}
                                                onChange={(e) => {
                                                    const next = [...blueprint.characters];
                                                    next[idx] = { ...char, personality: e.target.value };
                                                    setBlueprint((prev) => ({ ...prev, characters: next }));
                                                }}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl p-2.5 text-xs text-gray-200"
                                            />
                                        </div>

                                        {/* ComfyUI Visual Tags */}
                                        <div className="space-y-1.5 p-3 rounded-xl bg-purple-950/20 border border-purple-500/20">
                                            <label className="text-3xs font-bold uppercase tracking-wider text-purple-300 flex items-center gap-1">
                                                <Tag size={11} /> ComfyUI Visual Tags (comma-separated prompt tokens)
                                            </label>
                                            <input
                                                type="text"
                                                value={(char.visual_tags || []).join(', ')}
                                                onChange={(e) => {
                                                    const tags = e.target.value.split(',').map((t) => t.trim()).filter(Boolean);
                                                    const next = [...blueprint.characters];
                                                    next[idx] = { ...char, visual_tags: tags };
                                                    setBlueprint((prev) => ({ ...prev, characters: next }));
                                                }}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-purple-200"
                                            />
                                        </div>

                                        {/* Wardrobe Presets */}
                                        {char.wardrobe && char.wardrobe.length > 0 && (
                                            <div className="space-y-1.5">
                                                <label className="text-3xs font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1">
                                                    <Shirt size={11} /> Wardrobe Presets ({char.wardrobe.length})
                                                </label>
                                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                                    {char.wardrobe.map((w, widx) => (
                                                        <div key={widx} className="p-2 rounded-xl bg-gray-900/70 border border-white/5 space-y-0.5">
                                                            <div className="font-bold text-2xs text-gray-200">{w.name}</div>
                                                            <div className="text-3xs text-gray-400">{w.outfit}</div>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ))}

                                {/* Suggested Persona */}
                                <div className="glass-panel rounded-2xl p-4 border border-white/10 space-y-3 text-xs">
                                    <div className="flex items-center justify-between">
                                        <h4 className="text-xs font-bold text-sky-300 flex items-center gap-1.5">
                                            <User size={14} /> Suggested {`{{user}}`} Persona: {blueprint.persona?.name || 'Companion'}
                                        </h4>
                                        <label className="flex items-center gap-1.5 text-2xs text-sky-200 cursor-pointer">
                                            <input
                                                type="checkbox"
                                                checked={Boolean(blueprint.persona?.create)}
                                                onChange={(e) =>
                                                    setBlueprint((prev) => ({
                                                        ...prev,
                                                        persona: { ...prev.persona, create: e.target.checked },
                                                    }))
                                                }
                                                className="accent-sky-500"
                                            />
                                            <span>Save to Persona Vault</span>
                                        </label>
                                    </div>
                                    <p className="text-2xs text-gray-300">{blueprint.persona?.description}</p>
                                </div>
                            </div>
                        )}

                        {/* TAB 2: SCENARIOS & GREETINGS */}
                        {activeIntegrationTab === 'scenarios' && (
                            <ScenariosMappingTab
                                scenarios={blueprint.scenarios || []}
                                onChangeScenarios={(next) => setBlueprint((prev) => ({ ...prev, scenarios: next }))}
                                onRefineWithLLM={handleRefineScenarios}
                                onEnrichGreeting={(scenarioId, text) => handleEnrichField(`scenario_${scenarioId}`, text)}
                                isRefining={isRefiningScenarios}
                            />
                        )}

                        {/* TAB 3: DIRECTOR & STATEKEEPER TURN-0 */}
                        {activeIntegrationTab === 'statekeeper' && (
                            <StatekeeperTurn0Tab
                                snapshot={blueprint.initial_state_snapshot || {}}
                                lockedFields={lockedFields}
                                onChangeSnapshot={(snap) =>
                                    setBlueprint((prev) => ({
                                        ...prev,
                                        initial_state_snapshot: snap,
                                    }))
                                }
                                onToggleLock={handleToggleLock}
                                onSynthesizeTurn0={handleSynthesizeTurn0}
                                isSynthesizing={isSynthesizingTurn0}
                            />
                        )}

                        {/* TAB 4: WORLD & LOCATIONS */}
                        {activeIntegrationTab === 'world' && (
                            <div className="space-y-4 text-xs">
                                <div className="glass-panel rounded-2xl p-4 border border-white/10 space-y-3">
                                    <div className="flex items-center justify-between gap-2">
                                        <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                            <Globe2 size={16} className="text-emerald-400" />
                                            World Container
                                        </h3>
                                        <button
                                            type="button"
                                            onClick={handleGenerateWorldLore}
                                            disabled={isGeneratingWorldLore}
                                            className="px-3 py-1 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/30 text-emerald-200 text-2xs font-semibold flex items-center gap-1.5"
                                        >
                                            <Sparkles size={12} className={isGeneratingWorldLore ? 'animate-spin' : ''} />
                                            <span>{isGeneratingWorldLore ? 'Generating...' : '✨ Generate World & Locations'}</span>
                                        </button>
                                    </div>

                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                        <div>
                                            <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                World Name
                                            </label>
                                            <input
                                                type="text"
                                                value={blueprint.world?.name || ''}
                                                onChange={(e) =>
                                                    setBlueprint((prev) => ({
                                                        ...prev,
                                                        world: { ...prev.world, name: e.target.value },
                                                    }))
                                                }
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white"
                                            />
                                        </div>
                                        <div className="md:col-span-2">
                                            <div className="flex items-center justify-between">
                                                <label className="text-3xs font-bold uppercase tracking-wider text-gray-400">
                                                    World Premise &amp; Overview
                                                </label>
                                                <button
                                                    type="button"
                                                    onClick={() => handleEnrichField('world_description', blueprint.world?.description)}
                                                    disabled={enrichingFieldKey === 'world_description'}
                                                    className="text-3xs text-purple-300 hover:text-purple-200 font-semibold"
                                                >
                                                    ✨ Enrich
                                                </button>
                                            </div>
                                            <input
                                                type="text"
                                                value={blueprint.world?.description || ''}
                                                onChange={(e) =>
                                                    setBlueprint((prev) => ({
                                                        ...prev,
                                                        world: { ...prev.world, description: e.target.value },
                                                    }))
                                                }
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-200"
                                            />
                                        </div>
                                    </div>
                                </div>

                                {/* Locations List */}
                                <div className="glass-panel rounded-2xl p-4 border border-white/10 space-y-3">
                                    <h4 className="text-xs font-bold text-amber-300 flex items-center gap-1.5">
                                        <MapPin size={14} /> World Locations ({blueprint.locations?.length || 0})
                                    </h4>
                                    <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                                        {(blueprint.locations || []).map((loc, idx) => (
                                            <div key={idx} className="p-2.5 rounded-xl bg-gray-900/70 border border-white/5 space-y-1">
                                                <div className="flex items-center justify-between gap-2">
                                                    <input
                                                        type="text"
                                                        value={loc.name || ''}
                                                        onChange={(e) => {
                                                            const next = [...blueprint.locations];
                                                            next[idx] = { ...loc, name: e.target.value };
                                                            setBlueprint((prev) => ({ ...prev, locations: next }));
                                                        }}
                                                        className="bg-gray-900/80 border border-white/10 rounded-lg px-2 py-0.5 text-xs font-bold text-amber-200 flex-1"
                                                    />
                                                    <input
                                                        type="checkbox"
                                                        checked={loc.selected !== false}
                                                        onChange={(e) => {
                                                            const next = [...blueprint.locations];
                                                            next[idx] = { ...loc, selected: e.target.checked };
                                                            setBlueprint((prev) => ({ ...prev, locations: next }));
                                                        }}
                                                        className="accent-amber-500 rounded cursor-pointer"
                                                    />
                                                </div>
                                                <input
                                                    type="text"
                                                    value={loc.description || ''}
                                                    onChange={(e) => {
                                                        const next = [...blueprint.locations];
                                                        next[idx] = { ...loc, description: e.target.value };
                                                        setBlueprint((prev) => ({ ...prev, locations: next }));
                                                    }}
                                                    className="w-full bg-gray-900/50 border border-white/5 rounded-lg px-2 py-0.5 text-2xs text-gray-300"
                                                />
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* TAB 5: LOREBOOK & CODEX */}
                        {activeIntegrationTab === 'lorebook' && (
                            <div className="glass-panel rounded-2xl p-4 border border-white/10 space-y-3 text-xs">
                                <div className="flex items-center justify-between">
                                    <h3 className="text-sm font-bold text-purple-300 flex items-center gap-2">
                                        <BookOpen size={16} /> World Lorebook &amp; Codex ({blueprint.lorebook?.entries?.length || 0})
                                    </h3>
                                    <label className="flex items-center gap-1.5 text-2xs text-purple-200 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={Boolean(blueprint.lorebook?.create)}
                                            onChange={(e) =>
                                                setBlueprint((prev) => ({
                                                    ...prev,
                                                    lorebook: { ...prev.lorebook, create: e.target.checked },
                                                }))
                                            }
                                            className="accent-purple-500"
                                        />
                                        <span>Create Lorebook in World Vault</span>
                                    </label>
                                </div>

                                <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                                    {(blueprint.lorebook?.entries || []).map((entry, idx) => (
                                        <div key={idx} className="p-2.5 rounded-xl bg-gray-900/70 border border-white/5 space-y-1">
                                            <div className="flex items-center gap-1.5 flex-wrap">
                                                {(entry.keys || []).map((k, kidx) => (
                                                    <span key={kidx} className="px-1.5 py-0.2 rounded text-3xs font-mono bg-purple-500/20 text-purple-300 border border-purple-500/30">
                                                        {k}
                                                    </span>
                                                ))}
                                            </div>
                                            <p className="text-2xs text-gray-300 font-mono leading-relaxed line-clamp-3">
                                                {entry.content}
                                            </p>
                                        </div>
                                    ))}
                                    {(!blueprint.lorebook?.entries || blueprint.lorebook.entries.length === 0) && (
                                        <div className="text-center text-gray-500 py-6 italic text-2xs">
                                            No embedded lorebook entries detected. Run Auto-Architect to synthesize codex entries.
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* TAB 6: STORY SANDBOX (FOR LONG INGESTED STORIES) */}
                        {activeIntegrationTab === 'story' && blueprint.story_chapters && (
                            <div className="glass-panel rounded-2xl p-4 border border-white/10 space-y-3 text-xs">
                                <div className="flex items-center justify-between">
                                    <h3 className="text-sm font-bold text-sky-300 flex items-center gap-2">
                                        <BookOpen size={16} /> Chained Story Chapters ({blueprint.story_chapters.length})
                                    </h3>
                                    <span className="text-2xs font-mono text-gray-400">
                                        Total Words: {blueprint.total_words?.toLocaleString()} ({blueprint.chunk_count} chunks)
                                    </span>
                                </div>

                                <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                                    {blueprint.story_chapters.map((ch, idx) => (
                                        <div key={idx} className="p-3 rounded-xl bg-gray-900/70 border border-white/5 space-y-1">
                                            <div className="flex items-center justify-between font-bold text-gray-200 text-xs">
                                                <span>{ch.title}</span>
                                                <span className="text-3xs font-mono text-gray-400">{ch.word_count} words</span>
                                            </div>
                                            <p className="text-2xs text-gray-300 line-clamp-3 leading-relaxed">
                                                {ch.synopsis}
                                            </p>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* BOTTOM COMMIT & LAUNCH BAR */}
                        <div className="glass-panel rounded-2xl p-4 border border-emerald-500/40 bg-emerald-950/20 flex flex-wrap items-center justify-between gap-4 shadow-xl">
                            <div className="flex flex-wrap items-center gap-4 text-xs text-gray-200">
                                <label className="flex items-center gap-2 cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={launchChat}
                                        onChange={(e) => setLaunchChat(e.target.checked)}
                                        className="accent-emerald-500 rounded"
                                    />
                                    <span>Launch Turn-0 Roleplay Chat Immediately</span>
                                </label>
                                <label className="flex items-center gap-2 cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={launchStory}
                                        onChange={(e) => setLaunchStory(e.target.checked)}
                                        className="accent-purple-500 rounded"
                                    />
                                    <span>Also Create Story Sandbox Chapter</span>
                                </label>
                            </div>

                            <button
                                type="button"
                                onClick={handleCommitBlueprint}
                                disabled={commitBlueprintMut.isPending}
                                className="px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-gray-950 font-extrabold text-xs flex items-center gap-2 shadow-lg disabled:opacity-50 transition-all transform hover:scale-[1.02]"
                            >
                                {commitBlueprintMut.isPending ? (
                                    <Loader2 size={15} className="animate-spin" />
                                ) : (
                                    <ArrowRight size={15} />
                                )}
                                Commit Blueprint &amp; Launch into World Vault
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* TAB 3: WORLD CROSSOVER & TRANSMIGRATION STUDIO */}
            {activeTab === 'crossover' && (
                <div className="space-y-5">
                    <div className="glass-panel rounded-2xl p-5 border border-white/10 space-y-4">
                        <h3 className="text-sm font-bold text-white flex items-center gap-2">
                            <Globe2 size={16} className="text-cyan-400" /> Configure Multiverse Crossover / Transmigration
                        </h3>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            {/* Traveler Characters */}
                            <div className="space-y-2">
                                <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                                    1. Select Traveler Character(s) (Origin World)
                                </label>
                                <div className="grid grid-cols-2 gap-1.5 max-h-48 overflow-y-auto p-2 bg-black/30 rounded-xl border border-white/10">
                                    {characters.map((c) => {
                                        const selected = travelerIds.includes(c.id);
                                        return (
                                            <button
                                                key={c.id}
                                                type="button"
                                                onClick={() => handleToggleTraveler(c.id)}
                                                className={clsx(
                                                    'px-2.5 py-1.5 rounded-lg text-xs text-left border transition-colors truncate',
                                                    selected
                                                        ? 'bg-cyan-500/25 border-cyan-400 text-cyan-200 font-semibold'
                                                        : 'bg-gray-900/60 border-white/5 text-gray-300 hover:border-white/20'
                                                )}
                                            >
                                                {c.name}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>

                            {/* Destination World & Location */}
                            <div className="space-y-3">
                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-wider text-gray-300 mb-1">
                                        2. Select Destination World
                                    </label>
                                    <select
                                        value={targetWorldId}
                                        onChange={(e) => {
                                            setTargetWorldId(e.target.value);
                                            setTargetLocationId('');
                                        }}
                                        className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2 text-xs text-gray-200"
                                    >
                                        <option value="">— Choose destination world —</option>
                                        {worlds.map((w) => (
                                            <option key={w.id} value={w.id}>
                                                {w.name}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                {targetWorldLocations.length > 0 && (
                                    <div>
                                        <label className="block text-xs font-bold uppercase tracking-wider text-gray-300 mb-1">
                                            Arrival Location (Optional)
                                        </label>
                                        <select
                                            value={targetLocationId}
                                            onChange={(e) => setTargetLocationId(e.target.value)}
                                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2 text-xs text-gray-200"
                                        >
                                            <option value="">— Default World Entry Point —</option>
                                            {targetWorldLocations.map((l) => (
                                                <option key={l.id} value={l.id}>
                                                    {l.name}
                                                </option>
                                            ))}
                                        </select>
                                    </div>
                                )}

                                <div>
                                    <label className="block text-xs font-bold uppercase tracking-wider text-gray-300 mb-1">
                                        Include Resident Characters (Optional)
                                    </label>
                                    <div className="flex flex-wrap gap-1.5">
                                        {characters
                                            .filter((c) => !travelerIds.includes(c.id))
                                            .slice(0, 8)
                                            .map((c) => (
                                                <button
                                                    key={c.id}
                                                    type="button"
                                                    onClick={() => handleToggleResident(c.id)}
                                                    className={clsx(
                                                        'px-2 py-1 rounded text-2xs border',
                                                        residentIds.includes(c.id)
                                                            ? 'bg-purple-500/25 border-purple-400 text-purple-200 font-semibold'
                                                            : 'bg-gray-900 border-white/10 text-gray-400'
                                                    )}
                                                >
                                                    {c.name}
                                                </button>
                                            ))}
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Archetype Cards */}
                        <div className="space-y-2">
                            <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                                3. Crossover / Transmigration Archetype
                            </label>
                            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                                {ARCHETYPE_CARDS.map((card) => (
                                    <button
                                        key={card.id}
                                        type="button"
                                        onClick={() => setArchetype(card.id)}
                                        className={clsx(
                                            'p-3 rounded-xl border text-left transition-all',
                                            archetype === card.id
                                                ? 'bg-cyan-500/15 border-cyan-400 text-white'
                                                : 'bg-black/30 border-white/10 text-gray-400 hover:border-white/20'
                                        )}
                                    >
                                        <div className="text-xs font-bold text-cyan-300">{card.label}</div>
                                        <p className="text-2xs text-gray-400 mt-1 line-clamp-3">{card.summary}</p>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div>
                            <label className="block text-xs font-bold uppercase tracking-wider text-gray-300 mb-1">
                                Custom Crossover Premise / Catalyst (Optional)
                            </label>
                            <input
                                type="text"
                                value={customPremise}
                                onChange={(e) => setCustomPremise(e.target.value)}
                                placeholder="e.g. Their cybernetic implants react strangely to the destination world's mana leylines..."
                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2 text-xs text-gray-200"
                            />
                        </div>

                        <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-white/5">
                            {targetWorldId && (
                                <button
                                    type="button"
                                    onClick={async () => {
                                        const res = await runWorldTickMut.mutateAsync({
                                            worldId: targetWorldId,
                                            timeAdvanceLabel: '+1 Day',
                                        });
                                        setWorldTickResult(res);
                                    }}
                                    disabled={runWorldTickMut.isPending}
                                    className="px-3 py-2 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-xs font-semibold flex items-center gap-1.5"
                                >
                                    <Clock size={13} /> Simulate Destination World Tick (+1 Day)
                                </button>
                            )}
                            <div className="flex items-center gap-2 ml-auto">
                                <button
                                    type="button"
                                    onClick={() => handlePreviewCrossover(false)}
                                    disabled={crossoverPreviewMut.isPending}
                                    className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-white text-xs font-semibold flex items-center gap-1.5"
                                >
                                    {crossoverPreviewMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                                    Preview Crossover
                                </button>
                                <button
                                    type="button"
                                    onClick={() => handlePreviewCrossover(true)}
                                    disabled={crossoverPreviewMut.isPending}
                                    className="px-4 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-gray-950 text-xs font-bold flex items-center gap-1.5 shadow-lg"
                                >
                                    <ArrowRight size={13} /> Launch Crossover Chat Now
                                </button>
                            </div>
                        </div>
                    </div>

                    {worldTickResult && (
                        <div className="glass-panel rounded-2xl p-4 border border-amber-500/30 space-y-2">
                            <div className="text-xs font-bold text-amber-300 uppercase tracking-wider">
                                Living World Simulation — {worldTickResult.world_name} ({worldTickResult.time_advance_label})
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                                {(worldTickResult.events || []).map((ev, i) => (
                                    <div key={i} className="bg-black/30 rounded-xl p-2.5 border border-white/10 text-xs space-y-1">
                                        <div className="font-bold text-white">{ev.actor} @ {ev.location}</div>
                                        <p className="text-gray-300 text-2xs">{ev.event}</p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {crossoverPreview && (
                        <div className="glass-panel rounded-2xl p-5 border border-cyan-500/30 space-y-3">
                            <div className="flex items-center justify-between">
                                <h4 className="text-sm font-bold text-cyan-300">{crossoverPreview.scenario?.title}</h4>
                                <span className="text-2xs font-mono text-gray-400">{crossoverPreview.archetype_label}</span>
                            </div>
                            <p className="text-xs text-gray-300">{crossoverPreview.scenario?.description}</p>
                            <div className="bg-black/40 rounded-xl p-3 border border-white/10 text-xs text-gray-200 whitespace-pre-line">
                                {crossoverPreview.scenario?.first_mes}
                            </div>
                            <div className="bg-cyan-950/30 rounded-xl p-3 border border-cyan-500/20 text-2xs text-cyan-200">
                                <b>World Crossover Rules Injected into Prompt:</b> {crossoverPreview.crossover_context}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
