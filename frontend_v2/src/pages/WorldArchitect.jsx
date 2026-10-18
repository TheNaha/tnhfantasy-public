import clsx from 'clsx';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
    Sparkles, Upload, FileText, Globe2, Users, MapPin, BookOpen, Shield, Clock,
    Check, Plus, ArrowRight, Loader2, Eye, Wand2, Layers, Compass, Shirt, User,
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
} from '../hooks/useWorldVault';

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

    // Card Onboarding State
    const [cardFile, setCardFile] = useState(null);
    const [selectedExistingCharId, setSelectedExistingCharId] = useState(preselectedCharId);
    const [useVision, setUseVision] = useState(true);

    // Document / Story Ingestion State
    const [docFile, setDocFile] = useState(null);
    const [storyTitle, setStoryTitle] = useState('');
    const [storyRawText, setStoryRawText] = useState('');

    // Shared Editable Blueprint State
    const [blueprint, setBlueprint] = useState(null);
    const [launchChat, setLaunchChat] = useState(true);
    const [launchStory, setLaunchStory] = useState(false);
    const [errorMsg, setErrorMsg] = useState('');

    // Crossover Studio State
    const [travelerIds, setTravelerIds] = useState([]);
    const [targetWorldId, setTargetWorldId] = useState('');
    const [targetLocationId, setTargetLocationId] = useState('');
    const [residentIds, setResidentIds] = useState([]);
    const [archetype, setArchetype] = useState('rift_portal');
    const [customPremise, setCustomPremise] = useState('');
    const [crossoverPreview, setCrossoverPreview] = useState(null);
    const [worldTickResult, setWorldTickResult] = useState(null);

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
        try {
            const res = await analyzeDocument.mutateAsync({
                file: docFile,
                rawText: storyRawText,
                title: storyTitle,
            });
            setBlueprint(res);
            setLaunchChat(true);
            setLaunchStory(true);
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to extract world blueprint from story.');
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
                navigate(`/chats?chatId=${res.chat_id}`);
            } else if (res.story_id) {
                navigate(`/stories?storyId=${res.story_id}`);
            } else if (res.world_id) {
                navigate(`/worlds/${res.world_id}`);
            }
        } catch (err) {
            setErrorMsg(err?.message || 'Failed to commit World Blueprint.');
        }
    };

    const handlePreviewCrossover = async (commitImmediately = false) => {
        setErrorMsg('');
        if (travelerIds.length === 0 || !targetWorldId) {
            setErrorMsg('Select at least one Traveler Character and a Destination World.');
            return;
        }
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
            setErrorMsg(err?.message || 'Failed to synthesize World Crossover.');
        }
    };

    const handleToggleTraveler = (cid) => {
        setTravelerIds((prev) =>
            prev.includes(cid) ? prev.filter((x) => x !== cid) : [...prev, cid]
        );
    };

    const handleToggleResident = (cid) => {
        setResidentIds((prev) =>
            prev.includes(cid) ? prev.filter((x) => x !== cid) : [...prev, cid]
        );
    };

    const targetWorldLocations = targetWorldId
        ? locations.filter((l) => l.world_id === targetWorldId)
        : [];

    const isAnalyzing =
        analyzeCard.isPending ||
        analyzeExistingChar.isPending ||
        analyzeDocument.isPending;

    return (
        <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-4">
                <div>
                    <div className="flex items-center gap-2 text-emerald-400 text-xs font-bold uppercase tracking-widest mb-1">
                        <Wand2 size={14} /> World Vault Onboarding &amp; Multiverse Studio
                    </div>
                    <h1 className="text-2xl font-bold text-white flex items-center gap-2">
                        World Architect Studio
                    </h1>
                    <p className="text-sm text-gray-400 mt-1">
                        Transform a SillyTavern card or PDF/story into a living World with Vision-extracted outfits, Locations, Scenarios, Personas, Skillsets, and Turn-0 Statekeeper state — or launch a World Crossover.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Link
                        to="/worlds"
                        className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-gray-300"
                    >
                        View Worlds
                    </Link>
                    <Link
                        to="/characters"
                        className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-gray-300"
                    >
                        View Characters
                    </Link>
                </div>
            </div>

            {/* Mode Tabs */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                {[
                    {
                        id: 'card',
                        label: '1. Card → Rich World',
                        sub: 'SillyTavern PNG/JSON/CharX + Vision LLM',
                        icon: Upload,
                    },
                    {
                        id: 'document',
                        label: '2. Story / PDF → World',
                        sub: 'Extract Cast, Places, Lore & Chapters',
                        icon: FileText,
                    },
                    {
                        id: 'crossover',
                        label: '3. World Crossover Studio',
                        sub: 'Transmigrate Characters Across Worlds',
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
                <div className="p-3 rounded-xl bg-red-500/15 border border-red-500/30 text-red-200 text-xs font-medium">
                    {errorMsg}
                </div>
            )}

            {/* TAB 1: CARD -> WORLD */}
            {activeTab === 'card' && (
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
                                Use <b>Vision LLM</b> on embedded card portrait to extract visual tags, outfit, wardrobe presets &amp; backdrop setting
                            </span>
                        </label>

                        <button
                            type="submit"
                            disabled={isAnalyzing}
                            className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center gap-2 shadow-lg disabled:opacity-50"
                        >
                            {isAnalyzing ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                            Analyze &amp; Generate World Blueprint
                        </button>
                    </div>
                </form>
            )}

            {/* TAB 2: DOCUMENT / PDF / STORY -> WORLD */}
            {activeTab === 'document' && (
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
                        <label className="block text-xs font-bold uppercase tracking-wider text-gray-300">
                            Or Paste Story Prose / Lore Chapter Directly
                        </label>
                        <textarea
                            rows={5}
                            value={storyRawText}
                            onChange={(e) => setStoryRawText(e.target.value)}
                            placeholder="Paste a chapter, short story, or worldbuilding document here to extract playable characters, locations, lorebook entries, and scenarios..."
                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl p-3 text-xs text-gray-200 focus:outline-none focus:border-purple-500/50"
                        />
                    </div>

                    <div className="flex justify-end">
                        <button
                            type="submit"
                            disabled={isAnalyzing}
                            className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-bold flex items-center gap-2 shadow-lg disabled:opacity-50"
                        >
                            {isAnalyzing ? <Loader2 size={14} className="animate-spin" /> : <BookOpen size={14} />}
                            Extract Playable World &amp; Cast
                        </button>
                    </div>
                </form>
            )}

            {/* SHARED BLUEPRINT REVIEW & EDITOR (FOR TABS 1 & 2) */}
            {(activeTab === 'card' || activeTab === 'document') && blueprint && (
                <div className="space-y-5">
                    {/* Telemetry Banner */}
                    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-xs">
                        <div className="flex items-center gap-2 text-emerald-200 font-medium">
                            <Check size={14} className="text-emerald-400" />
                            <span>
                                World Blueprint Ready — <b>{blueprint.characters?.length || 0}</b> Character(s),{' '}
                                <b>{blueprint.locations?.length || 0}</b> Location(s),{' '}
                                <b>{blueprint.scenarios?.length || 0}</b> Scenario(s),{' '}
                                <b>{blueprint.lorebook?.entries?.length || 0}</b> Lore Entries
                            </span>
                        </div>
                        <div className="text-2xs font-mono text-emerald-300">
                            Engine: {blueprint.analysis_meta?.engine_used || 'heuristic'}
                            {blueprint.analysis_meta?.vision_used ? ' + Vision LLM' : ''}
                        </div>
                    </div>

                    {/* 1. World Target (Create vs Merge) */}
                    <div className="glass-panel rounded-2xl p-5 border border-white/10 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                <Globe2 size={15} className="text-emerald-400" /> 1. World Container
                            </h3>
                            <div className="flex items-center gap-2 text-xs">
                                <button
                                    type="button"
                                    onClick={() =>
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            world: { ...prev.world, mode: 'create' },
                                        }))
                                    }
                                    className={clsx(
                                        'px-2.5 py-1 rounded-lg border text-xs',
                                        blueprint.world?.mode !== 'merge'
                                            ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-200 font-semibold'
                                            : 'bg-gray-900 border-white/10 text-gray-400'
                                    )}
                                >
                                    Create New World
                                </button>
                                <button
                                    type="button"
                                    onClick={() =>
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            world: {
                                                ...prev.world,
                                                mode: 'merge',
                                                existing_world_id: prev.world?.existing_world_id || worlds[0]?.id || '',
                                            },
                                        }))
                                    }
                                    disabled={worlds.length === 0}
                                    className={clsx(
                                        'px-2.5 py-1 rounded-lg border text-xs disabled:opacity-40',
                                        blueprint.world?.mode === 'merge'
                                            ? 'bg-purple-500/20 border-purple-500/40 text-purple-200 font-semibold'
                                            : 'bg-gray-900 border-white/10 text-gray-400'
                                    )}
                                >
                                    Merge Into Existing World
                                </button>
                            </div>
                        </div>

                        {blueprint.world?.mode === 'merge' ? (
                            <div>
                                <label className="block text-2xs uppercase text-gray-400 mb-1">Select Target World</label>
                                <select
                                    value={blueprint.world?.existing_world_id || ''}
                                    onChange={(e) =>
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            world: { ...prev.world, existing_world_id: e.target.value },
                                        }))
                                    }
                                    className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2 text-xs text-gray-200"
                                >
                                    {worlds.map((w) => (
                                        <option key={w.id} value={w.id}>
                                            {w.name}
                                        </option>
                                    ))}
                                </select>
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                                <div>
                                    <label className="block text-2xs uppercase text-gray-400 mb-1">World Name</label>
                                    <input
                                        type="text"
                                        value={blueprint.world?.name || ''}
                                        onChange={(e) =>
                                            setBlueprint((prev) => ({
                                                ...prev,
                                                world: { ...prev.world, name: e.target.value },
                                            }))
                                        }
                                        className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2 text-xs text-white"
                                    />
                                </div>
                                <div className="md:col-span-2">
                                    <label className="block text-2xs uppercase text-gray-400 mb-1">World Description &amp; Premise</label>
                                    <input
                                        type="text"
                                        value={blueprint.world?.description || ''}
                                        onChange={(e) =>
                                            setBlueprint((prev) => ({
                                                ...prev,
                                                world: { ...prev.world, description: e.target.value },
                                            }))
                                        }
                                        className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-2 text-xs text-gray-200"
                                    />
                                </div>
                            </div>
                        )}
                    </div>

                    {/* 2. Characters & Visual Tags / Skillsets */}
                    <div className="glass-panel rounded-2xl p-5 border border-white/10 space-y-3">
                        <h3 className="text-sm font-bold text-white flex items-center gap-2">
                            <Users size={15} className="text-purple-400" /> 2. Extracted Cast &amp; Visual / Skill Profiles
                        </h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {(blueprint.characters || []).map((char, idx) => (
                                <div key={idx} className="bg-black/30 rounded-xl p-3.5 border border-white/10 space-y-2">
                                    <div className="flex items-start gap-3">
                                        {char.avatar_base64 && (
                                            <img
                                                src={`data:image/png;base64,${char.avatar_base64}`}
                                                alt={char.name}
                                                className="w-14 h-14 rounded-xl object-cover border border-white/15 shrink-0"
                                            />
                                        )}
                                        <div className="flex-1 min-w-0 space-y-1">
                                            <div className="flex items-center justify-between gap-2">
                                                <input
                                                    type="text"
                                                    value={char.name || ''}
                                                    onChange={(e) => {
                                                        const next = [...blueprint.characters];
                                                        next[idx] = { ...char, name: e.target.value };
                                                        setBlueprint((prev) => ({ ...prev, characters: next }));
                                                    }}
                                                    className="bg-gray-900/80 border border-white/10 rounded px-2 py-1 text-xs font-bold text-white w-full"
                                                />
                                                <input
                                                    type="checkbox"
                                                    checked={char.selected !== false}
                                                    onChange={(e) => {
                                                        const next = [...blueprint.characters];
                                                        next[idx] = { ...char, selected: e.target.checked };
                                                        setBlueprint((prev) => ({ ...prev, characters: next }));
                                                    }}
                                                    className="accent-purple-500"
                                                />
                                            </div>
                                            <div className="grid grid-cols-2 gap-1.5 text-2xs">
                                                <input
                                                    type="text"
                                                    value={char.default_location || ''}
                                                    onChange={(e) => {
                                                        const next = [...blueprint.characters];
                                                        next[idx] = { ...char, default_location: e.target.value };
                                                        setBlueprint((prev) => ({ ...prev, characters: next }));
                                                    }}
                                                    placeholder="Default Location"
                                                    className="bg-gray-900/60 border border-white/5 rounded px-2 py-1 text-gray-300"
                                                />
                                                <input
                                                    type="text"
                                                    value={char.default_time || ''}
                                                    onChange={(e) => {
                                                        const next = [...blueprint.characters];
                                                        next[idx] = { ...char, default_time: e.target.value };
                                                        setBlueprint((prev) => ({ ...prev, characters: next }));
                                                    }}
                                                    placeholder="Default Time"
                                                    className="bg-gray-900/60 border border-white/5 rounded px-2 py-1 text-gray-300"
                                                />
                                            </div>
                                        </div>
                                    </div>

                                    <div>
                                        <label className="block text-2xs uppercase text-gray-400 mb-0.5">
                                            ComfyUI Visual Tags (comma-separated)
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
                                            className="w-full bg-gray-900/70 border border-white/10 rounded px-2 py-1 text-2xs text-purple-200"
                                        />
                                    </div>

                                    <div>
                                        <label className="block text-2xs uppercase text-gray-400 mb-0.5">
                                            Character Skillset (comma-separated)
                                        </label>
                                        <input
                                            type="text"
                                            value={(char.character_skills || []).join(', ')}
                                            onChange={(e) => {
                                                const skills = e.target.value.split(',').map((s) => s.trim()).filter(Boolean);
                                                const next = [...blueprint.characters];
                                                next[idx] = { ...char, character_skills: skills };
                                                setBlueprint((prev) => ({
                                                    ...prev,
                                                    characters: next,
                                                    ...(idx === 0
                                                        ? {
                                                              initial_state_snapshot: {
                                                                  ...prev.initial_state_snapshot,
                                                                  character_skills: skills,
                                                              },
                                                          }
                                                        : {}),
                                                }));
                                            }}
                                            className="w-full bg-gray-900/70 border border-white/10 rounded px-2 py-1 text-2xs text-emerald-200"
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* 3. Locations & Scenarios Grid */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* Locations */}
                        <div className="glass-panel rounded-2xl p-5 border border-white/10 space-y-3">
                            <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                <MapPin size={15} className="text-amber-400" /> 3. World Locations ({blueprint.locations?.length || 0})
                            </h3>
                            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                                {(blueprint.locations || []).map((loc, idx) => (
                                    <div key={idx} className="bg-black/30 rounded-xl p-2.5 border border-white/10 space-y-1">
                                        <div className="flex items-center justify-between gap-2">
                                            <input
                                                type="text"
                                                value={loc.name || ''}
                                                onChange={(e) => {
                                                    const next = [...blueprint.locations];
                                                    next[idx] = { ...loc, name: e.target.value };
                                                    setBlueprint((prev) => ({ ...prev, locations: next }));
                                                }}
                                                className="bg-gray-900/80 border border-white/10 rounded px-2 py-1 text-xs font-semibold text-amber-200 flex-1"
                                            />
                                            <input
                                                type="checkbox"
                                                checked={loc.selected !== false}
                                                onChange={(e) => {
                                                    const next = [...blueprint.locations];
                                                    next[idx] = { ...loc, selected: e.target.checked };
                                                    setBlueprint((prev) => ({ ...prev, locations: next }));
                                                }}
                                                className="accent-amber-500"
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
                                            className="w-full bg-gray-900/60 border border-white/5 rounded px-2 py-1 text-2xs text-gray-300"
                                        />
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Scenarios from Greetings */}
                        <div className="glass-panel rounded-2xl p-5 border border-white/10 space-y-3">
                            <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                <Sparkles size={15} className="text-cyan-400" /> 4. Playable Scenarios ({blueprint.scenarios?.length || 0})
                            </h3>
                            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                                {(blueprint.scenarios || []).map((scen, idx) => (
                                    <div key={idx} className="bg-black/30 rounded-xl p-2.5 border border-white/10 space-y-1">
                                        <div className="flex items-center justify-between gap-2">
                                            <input
                                                type="text"
                                                value={scen.title || ''}
                                                onChange={(e) => {
                                                    const next = [...blueprint.scenarios];
                                                    next[idx] = { ...scen, title: e.target.value };
                                                    setBlueprint((prev) => ({ ...prev, scenarios: next }));
                                                }}
                                                className="bg-gray-900/80 border border-white/10 rounded px-2 py-1 text-xs font-semibold text-cyan-200 flex-1"
                                            />
                                            <input
                                                type="checkbox"
                                                checked={scen.selected !== false}
                                                onChange={(e) => {
                                                    const next = [...blueprint.scenarios];
                                                    next[idx] = { ...scen, selected: e.target.checked };
                                                    setBlueprint((prev) => ({ ...prev, scenarios: next }));
                                                }}
                                                className="accent-cyan-500"
                                            />
                                        </div>
                                        <p className="text-2xs text-gray-400 line-clamp-2">{scen.first_mes || scen.description}</p>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* 5. Turn-0 Statekeeper Snapshot & Suggested Persona */}
                    <div className="glass-panel rounded-2xl p-5 border border-emerald-500/25 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="text-sm font-bold text-emerald-300 flex items-center gap-2">
                                <Shield size={15} /> 5. Turn-0 Statekeeper Snapshot &amp; User Persona
                            </h3>
                            <label className="flex items-center gap-2 text-xs text-sky-300 cursor-pointer">
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
                                <span>Save Suggested <b>{'{{user}}'} Persona</b> ({blueprint.persona?.name || 'Protagonist'}) to Library</span>
                            </label>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
                            <div>
                                <label className="block text-2xs uppercase text-gray-400 mb-1">Opening Mood</label>
                                <input
                                    type="text"
                                    value={blueprint.initial_state_snapshot?.character_mood || ''}
                                    onChange={(e) =>
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            initial_state_snapshot: {
                                                ...prev.initial_state_snapshot,
                                                character_mood: e.target.value,
                                            },
                                        }))
                                    }
                                    className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-200"
                                />
                            </div>
                            <div>
                                <label className="block text-2xs uppercase text-gray-400 mb-1">Opening Activity</label>
                                <input
                                    type="text"
                                    value={blueprint.initial_state_snapshot?.current_activity || ''}
                                    onChange={(e) =>
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            initial_state_snapshot: {
                                                ...prev.initial_state_snapshot,
                                                current_activity: e.target.value,
                                            },
                                        }))
                                    }
                                    className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-200"
                                />
                            </div>
                            <div>
                                <label className="block text-2xs uppercase text-gray-400 mb-1">Opening Outfit</label>
                                <input
                                    type="text"
                                    value={blueprint.initial_state_snapshot?.character_outfit || ''}
                                    onChange={(e) =>
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            initial_state_snapshot: {
                                                ...prev.initial_state_snapshot,
                                                character_outfit: e.target.value,
                                            },
                                        }))
                                    }
                                    className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-200"
                                />
                            </div>
                            <div>
                                <label className="block text-2xs uppercase text-gray-400 mb-1">Relationship w/ User</label>
                                <input
                                    type="text"
                                    value={blueprint.initial_state_snapshot?.relationship_status || ''}
                                    onChange={(e) =>
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            initial_state_snapshot: {
                                                ...prev.initial_state_snapshot,
                                                relationship_status: e.target.value,
                                            },
                                        }))
                                    }
                                    className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-gray-200"
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs pt-1">
                            <div>
                                <label className="block text-2xs uppercase text-gray-400 mb-1">
                                    User / Persona Skillset (comma-separated)
                                </label>
                                <input
                                    type="text"
                                    value={(blueprint.initial_state_snapshot?.user_skills || []).join(', ')}
                                    onChange={(e) => {
                                        const skills = e.target.value.split(',').map((s) => s.trim()).filter(Boolean);
                                        setBlueprint((prev) => ({
                                            ...prev,
                                            persona: { ...prev.persona, skills },
                                            initial_state_snapshot: {
                                                ...prev.initial_state_snapshot,
                                                user_skills: skills,
                                            },
                                        }));
                                    }}
                                    className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1.5 text-xs text-sky-200"
                                />
                            </div>
                            <div className="flex items-center gap-3 pt-4">
                                <label className="flex items-center gap-2 cursor-pointer text-xs text-amber-300">
                                    <input
                                        type="checkbox"
                                        checked={Boolean(blueprint.initial_state_snapshot?.fate_check_enabled)}
                                        onChange={(e) =>
                                            setBlueprint((prev) => ({
                                                ...prev,
                                                initial_state_snapshot: {
                                                    ...prev.initial_state_snapshot,
                                                    fate_check_enabled: e.target.checked,
                                                },
                                            }))
                                        }
                                        className="accent-amber-500"
                                    />
                                    <span>Enable Fate / Skill Check Gate at Turn 0</span>
                                </label>
                            </div>
                        </div>
                    </div>

                    {/* Commit Bar */}
                    <div className="glass-panel rounded-2xl p-4 border border-emerald-500/40 bg-emerald-950/15 flex flex-wrap items-center justify-between gap-4">
                        <div className="flex flex-wrap items-center gap-4 text-xs text-gray-200">
                            <label className="flex items-center gap-2 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={launchChat}
                                    onChange={(e) => setLaunchChat(e.target.checked)}
                                    className="accent-emerald-500"
                                />
                                <span>Launch Turn-0 Roleplay Chat</span>
                            </label>
                            <label className="flex items-center gap-2 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={launchStory}
                                    onChange={(e) => setLaunchStory(e.target.checked)}
                                    className="accent-purple-500"
                                />
                                <span>Also Create Story Sandbox Chapter</span>
                            </label>
                        </div>

                        <button
                            type="button"
                            onClick={handleCommitBlueprint}
                            disabled={commitBlueprintMut.isPending}
                            className="px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-gray-950 font-bold text-xs flex items-center gap-2 shadow-lg disabled:opacity-50"
                        >
                            {commitBlueprintMut.isPending ? (
                                <Loader2 size={14} className="animate-spin" />
                            ) : (
                                <ArrowRight size={14} />
                            )}
                            Commit World Blueprint &amp; Launch
                        </button>
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
