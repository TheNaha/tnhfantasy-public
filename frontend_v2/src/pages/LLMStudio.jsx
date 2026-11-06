import React, { useState, useMemo, useEffect, useRef } from 'react';
import {
    Bot, Brain, Sparkles, Sliders, Play, Plus, Edit2, Trash2, Check,
    AlertCircle, Layers, Shield, Zap, RefreshCw, Cpu, CheckCircle2,
    Eye, ArrowRight, Activity, Clock, Compass, HelpCircle, Lock,
    ChevronDown, ChevronUp, Search, Filter, Server, CheckCircle, XCircle,
    Loader2, Save, RotateCcw, Volume2, Copy, GitBranch, Library
} from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
    useAgents,
    useAgentsWithVariants,
    getAgentAvatarUrl,
    useUploadAgentAvatar,
    useCreateAgent,
    useUpdateAgent,
    useDeleteAgent,
    useSimulateWorkflow,
    useAgentVariants,
    useCreateAgentVariant,
    useUpdateAgentVariant,
    useDeleteAgentVariant,
    useActivateAgentVariant,
    useLLMDefaultProvider,
    useLLMAvailableModels,
    useLLMRouting,
    useLLMRuntimeDefaults,
    useLLMDirectorGates,
} from '../hooks/useWorldVault';
import {
    useLLMProviderStatus,
    useSetLLMDefault,
    useLLMCatalog,
    useSetActiveModels,
    useEvaluateDirectorDecisions,
} from '../hooks/useLLMProviderStatus';
import useProvidersPageData from '../hooks/useProvidersPageData';
import { useSettings, useUpdateSettings } from '../store/settingsStore';
import { settingsApi } from '../api/settingsApi';
import { useConfirmation } from '../store/confirmationStore';
import { QueryErrorState } from '../components/common/QueryState';
import { copyToClipboard } from '../utils/clipboard';
import WorkflowTab from '../components/llm/WorkflowTab';
import LayaQuestionsTab from '../components/llm/LayaQuestionsTab';
import DecisionTraceTab from '../components/llm/DecisionTraceTab';

const GATE_CATEGORY_STYLES = {
    affect: { icon: Activity, color: 'text-pink-400 border-pink-500/20 bg-pink-500/5' },
    embodiment: { icon: Shield, color: 'text-amber-400 border-amber-500/20 bg-amber-500/5' },
    world: { icon: Compass, color: 'text-cyan-400 border-cyan-500/20 bg-cyan-500/5' },
    progression: { icon: Zap, color: 'text-emerald-400 border-emerald-500/20 bg-emerald-500/5' },
    memory: { icon: Brain, color: 'text-purple-400 border-purple-500/20 bg-purple-500/5' },
};

// Offline fallback only: the live registry comes from /llm/director/gates.
const FALLBACK_GATE_CATEGORIES = [
    {
        id: 'affect',
        title: 'Psychological & Affect',
        icon: Activity,
        color: 'text-pink-400 border-pink-500/20 bg-pink-500/5',
        gates: [
            { key: 'gate_character_mood', label: 'Character Mood', description: 'Emotional shift, vulnerability, hostility, or joy' },
            { key: 'gate_scene_tone', label: 'Scene Tone / Atmosphere', description: 'Environmental suspense, intimacy, danger, comedy' },
            { key: 'gate_relationship_dynamic', label: 'Relationship Dynamic', description: 'Trust, romantic intimacy, rivalry, or tension shift' },
        ]
    },
    {
        id: 'embodiment',
        title: 'Embodiment & Gear',
        icon: Shield,
        color: 'text-amber-400 border-amber-500/20 bg-amber-500/5',
        gates: [
            { key: 'gate_character_outfit', label: 'Outfit & Appearance', description: 'Armor damage, disrobing, disguise, clean clothes' },
            { key: 'gate_current_activity', label: 'Current Activity', description: 'Combat, crafting, traveling, dining, resting' },
            { key: 'gate_physical_condition', label: 'Physical Condition', description: 'Injuries, exhaustion, poison, healing, cyberware strain' },
            { key: 'gate_inventory_or_items', label: 'Inventory & Items', description: 'Acquiring, losing, consuming, or equipping gear' },
        ]
    },
    {
        id: 'world',
        title: 'World & Environment',
        icon: Compass,
        color: 'text-cyan-400 border-cyan-500/20 bg-cyan-500/5',
        gates: [
            { key: 'gate_world_clock', label: 'World Clock & Time', description: 'Day advancement, nightfall, rest period duration' },
            { key: 'gate_location_or_scene', label: 'Location & Setting', description: 'Fast-travel, entering room, terrain change' },
            { key: 'gate_weather_environment', label: 'Weather & Environment', description: 'Rainstorm, fog, blizzard, scorching heat' },
        ]
    },
    {
        id: 'progression',
        title: 'Progression & Stats',
        icon: Zap,
        color: 'text-emerald-400 border-emerald-500/20 bg-emerald-500/5',
        gates: [
            { key: 'gate_character_skills', label: 'Character Skills', description: 'New martial arts, spells, proficiencies demonstrated' },
            { key: 'gate_user_skills', label: 'User Persona Skills', description: 'User stat growth, training completion, reputation perks' },
            { key: 'gate_quests_or_goals', label: 'Quests & Goals', description: 'Mission progress, objectives completed, promises made' },
            { key: 'gate_social_status', label: 'Social Status & Standing', description: 'Faction rank, bounty, outlaw status, aristocracy' },
        ]
    },
    {
        id: 'memory',
        title: 'Narrative Knowledge',
        icon: Brain,
        color: 'text-purple-400 border-purple-500/20 bg-purple-500/5',
        gates: [
            { key: 'gate_durable_memory', label: 'Durable Memory', description: 'Key narrative revelation to store in episodic memory' },
            { key: 'gate_lore_discovery', label: 'Lore Discovery', description: 'Ancient history, world secrets, mythos unlocked' },
        ]
    }
];

const SYSTEM_PROMPT_CATEGORIES = [
    { id: 'all', label: 'All Prompts', color: 'text-gray-300' },
    { id: 'roleplay', label: 'Roleplay & Chat', badge: 'text-pink-400 bg-pink-500/10 border-pink-500/20' },
    { id: 'story', label: 'Story Sandbox', badge: 'text-amber-400 bg-amber-500/10 border-amber-500/20' },
    { id: 'world', label: 'World Vault & Memory', badge: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20' },
    { id: 'chargen', label: 'Character Creator', badge: 'text-purple-400 bg-purple-500/10 border-purple-500/20' },
    { id: 'generator', label: 'Prompt Studio', badge: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' },
];

const SYSTEM_PROMPT_DEFAULTS = {
    roleplay_default: 'You are {{char}} in an interactive roleplay with {{user}}. Stay fully in character, speaking naturally with sensory details and emotional reactions. Do not speak or act for {{user}}.',
    narrator: 'You are an atmospheric narrator depicting scenes, surroundings, and non-player interactions in vivid sensory prose.',
    suggest_instruction: 'Based on the conversation so far, suggest 3 distinct, concise, in-character actions or dialogue options the user could take next. Format as a bulleted list.',
    chat_impersonate: 'You are {user}, the human participant in this roleplay with {char}. Write ONE in-character message or action that {user} would realistically say or do next.{hint_clause} Output ONLY the raw message text — no labels, no quotes around the whole reply.',
    chat_scene_illustrate: 'You are an AI scene director for a roleplay chat. Read the following recent roleplay chat context and create a visual depiction of the current scene or the main character\'s action. Call the generate_image tool with a highly detailed ComfyUI image prompt (comma-separated Danbooru tags: subject, pose, lighting, camera angle, style, quality tags). After the image is generated, reply with a brief in-character caption for the image (1-2 sentences). If you are unable to call tools, output ONLY the image prompt text.',
    story_continue_default: 'You are an expert fantasy and fiction author. Continue the following interactive story in rich, descriptive literary prose. Maintain consistent tone, vivid sensory details, character motivations, and natural pacing.',
    story_action_rewrite: 'You are a literary novel editor and creative writing mentor. Rewrite the selected passage to enhance its prose rhythm, emotional nuance, vocabulary, and immersion while strictly preserving all plot events and dialogue.',
    story_action_expand: 'You are a creative fiction writer. Expand the selected story passage by adding vivid environmental atmosphere, visceral sensory details, nuanced internal monologue, and character mannerisms.',
    story_action_summarize: 'You are a concise literary summarizer. Synthesize the provided story text into an evocative, structured plot summary highlighting character developments, conflicts, and pivotal revelations.',
    story_illustrate: 'You are an AI visual art director. Analyze the provided story passage and generate a rich, highly descriptive visual depiction of the scene as comma-separated Danbooru and ComfyUI tags: character appearance, attire, poses, emotions, lighting, environment, and aesthetic quality tags.',
    story_parse: 'You are a narrative structure analyst. Read the provided text and parse it into structured chapters, scene beats, and character dialogue. Return strictly valid JSON.',
    story_compile: 'You are a literary novel editor. Given the raw roleplay transcript and scene milestones, compile and novelize this story into a cohesive, beautifully polished chapter. Write in immersive literary third-person past tense. Preserve the emotional depth, key character lines, and atmospheric details.',
    memory_extraction: 'You are an autobiographical memory extraction agent for an AI companion and roleplay system. Analyze the recent conversation between the user and the character. Extract durable, salient memories: character relationships, user preferences, disclosed secrets, emotional bonds, world facts, and ongoing promises. Return strictly valid JSON matching this schema: `{"memories": [{"content": "...", "category": "user_fact|relationship|promise|world_fact", "importance": 1-5, "emotional_valence": "positive|neutral|negative"}]}`.',
    world_onboarding: 'You are a master World Architect. Analyze the provided character profile or concept and design a complete, cohesive world vault blueprint with world lore, key factions, primary locations, and starter scenarios. Return strictly valid JSON.',
    world_lore_enrich: 'You are a mythologist and lore archivist. Given a lorebook entry and its world context, enrich the lore entry with historical background, cultural significance, related myths, and story hooks. Return strictly valid JSON with enriched entry details.',
    world_crossover: 'You are an imaginative crossover story weaver. Given two distinct characters, their worlds, and lorebooks, design a compelling crossover scenario, encounter premise, and conflict that brings them together naturally. Return strictly valid JSON.',
    world_tick: 'You are a world simulation engine. Given the current world state, active locations, and resident character statuses, simulate the passage of time: generate world events, faction rumors, and location atmosphere shifts. Return strictly valid JSON.',
    vision_avatar_analysis: 'You are an expert anime and fantasy art analyzer. Carefully examine the character image and output a detailed description of their physical appearance, hair, eyes, expression, clothing style, accessories, and a comma-separated list of Danbooru visual tags. Return strictly valid JSON.',
    magic_prompt: 'You are an expert AI prompt engineer specializing in Anime, Fantasy, and Cinematic digital art. Given a short user concept, expand it into a rich, comma-separated Danbooru and ComfyUI image prompt with detailed visual tags for subject, hair, eyes, clothing, expression, dynamic pose, cinematic lighting, intricate backdrop, and masterwork quality modifiers. Output ONLY the comma-separated prompt text.',
    charGenDescriptionPrompt: 'You are an expert character creator. Expand the provided character details into a rich, detailed background description. Return ONLY the text for the description, no markdown or extra chat.',
    charGenPersonalityPrompt: 'You are an expert character creator. Expand the provided character details into a detailed personality profile covering traits, quirks, and mannerisms. Return ONLY the text, no markdown.',
    charGenScenarioPrompt: 'You are an expert character creator. Create an engaging scenario/setting for this character based on their details. Return ONLY the text, no markdown.',
    charGenFirstMesPrompt: 'You are an expert character creator. Write an engaging first message/greeting from this character in their unique voice. Return ONLY the text, no markdown.',
    charGenMesExamplePrompt: 'You are an expert character creator. Write a few short dialogue examples showing how this character speaks. Use <START> to separate examples. Return ONLY the text, no markdown.',
    charGenSystemPromptPrompt: 'You are an expert character creator. Write a custom system prompt that instructs an AI how to play this character. Return ONLY the text, no markdown.',
    charGenVisualTagsPrompt: 'You are an expert character creator. Generate a comma-separated list of Danbooru-style visual tags that describe this character\'s appearance. Return ONLY the tags, no markdown.',
    charGenEnrichPrompt: 'You are an expert character creator. Read the provided character details and fill in ALL missing fields to enrich the character profile. Output MUST be valid JSON matching exactly these keys: "description", "personality", "scenario", "first_mes", "mes_example", "default_time", "default_location". Do not include markdown code blocks, just raw JSON.',
};

const SYSTEM_PROMPT_METADATA = [
    // Roleplay & Dialogue
    {
        key: 'roleplay_default',
        category: 'roleplay',
        label: 'Roleplay Default Block',
        desc: 'Default system instructions injected before character dialogue instructions in roleplay chats.',
        variables: ['{{char}}', '{{user}}', '{{persona}}'],
        rows: 4,
    },
    {
        key: 'narrator',
        category: 'roleplay',
        label: 'Narrator Scene Prompt',
        desc: 'Atmospheric scene director and environment narrator prompt for /narrate mode and narrator agent turns.',
        variables: ['{{user}}', '{{location}}'],
        rows: 3,
    },
    {
        key: 'suggest_instruction',
        category: 'roleplay',
        label: 'User Suggest Instruction',
        desc: 'Instructions used when suggesting next user action or dialogue options (/suggest).',
        variables: ['{{user}}', '{{char}}'],
        rows: 3,
    },
    {
        key: 'chat_impersonate',
        category: 'roleplay',
        label: 'Chat Impersonate Prompt',
        desc: 'User proxy prompt used to write the next in-character message or action on behalf of the human user.',
        variables: ['{user}', '{char}', '{hint_clause}'],
        rows: 3,
    },
    {
        key: 'chat_scene_illustrate',
        category: 'roleplay',
        label: 'Chat Scene Director & Selfie',
        desc: 'Instructions for the AI scene director to depict current roleplay scenes and character actions with ComfyUI Danbooru tags.',
        variables: ['generate_image', 'Danbooru tags', 'caption'],
        rows: 3,
    },

    // Interactive Story Sandbox
    {
        key: 'story_continue_default',
        category: 'story',
        label: 'Story Continuation Default',
        desc: 'Base system prompt for continuing the story prose in the interactive story editor.',
        variables: ['Story Context', 'Characters', 'Lore'],
        rows: 4,
    },
    {
        key: 'story_action_rewrite',
        category: 'story',
        label: 'Story Rewrite Action',
        desc: 'Instructions for creatively rewriting highlighted story passages with improved style and prose flow.',
        variables: ['Instruction', 'Passage Selection'],
        rows: 3,
    },
    {
        key: 'story_action_expand',
        category: 'story',
        label: 'Story Expand Action',
        desc: 'Elaborates on selected story scenes with sensory details, atmosphere, dialogue, and pacing.',
        variables: ['Instruction', 'Passage Selection'],
        rows: 3,
    },
    {
        key: 'story_action_summarize',
        category: 'story',
        label: 'Story Summarize Action',
        desc: 'Summarizes selected prose or entire chapters into concise narrative synopses.',
        variables: ['Chapter / Selection'],
        rows: 3,
    },
    {
        key: 'story_illustrate',
        category: 'story',
        label: 'Story Scene Illustrator',
        desc: 'Extracts visual scene descriptions and ComfyUI image tags from story excerpts.',
        variables: ['Story Beat', 'Danbooru Tags'],
        rows: 3,
    },
    {
        key: 'story_parse',
        category: 'story',
        label: 'Story Structure Parser',
        desc: 'Parses imported raw documents or prose into structured story chapters and scene beats.',
        variables: ['Imported Text', 'JSON Output'],
        rows: 3,
    },
    {
        key: 'story_compile',
        category: 'story',
        label: 'Story Novelizer & Compiler',
        desc: 'Compiles and novelizes multi-turn roleplay transcripts into cohesive, atmospheric literary chapters.',
        variables: ['Transcript', 'Location', 'JSON Output'],
        rows: 3,
    },

    // World Vault & Memory
    {
        key: 'memory_extraction',
        category: 'world',
        label: 'World Vault Memory Extraction',
        desc: 'Background pipeline prompt that extracts episodic memories, facts, secrets, and relationships from chat logs into pgvector.',
        variables: ['Recent Dialogue', 'Extracted Facts'],
        rows: 4,
    },
    {
        key: 'world_onboarding',
        category: 'world',
        label: 'World Architect Blueprint',
        desc: 'Synthesizes full World Blueprints (locations, lore, starting stats, Turn-0 activity) from character cards.',
        variables: ['Character Card', 'JSON Blueprint'],
        rows: 4,
    },
    {
        key: 'world_lore_enrich',
        category: 'world',
        label: 'World Lore Enricher',
        desc: 'Synthesizes evocative world lore, locations, and codex entries from character context.',
        variables: ['Character Data', 'Lorebook Entries'],
        rows: 3,
    },
    {
        key: 'world_crossover',
        category: 'world',
        label: 'World Crossover & Isekai Architect',
        desc: 'Designs crossover scenario premises, origin-destination physics, and Turn-0 encounters between disparate worlds.',
        variables: ['Origin World', 'Destination World', 'Travelers'],
        rows: 3,
    },
    {
        key: 'world_tick',
        category: 'world',
        label: 'Living World Simulation Tick',
        desc: 'Simulates the passage of time, generating off-screen autonomous NPC activities, events, and rumors.',
        variables: ['World State', 'NPCs', 'Locations'],
        rows: 3,
    },
    {
        key: 'vision_avatar_analysis',
        category: 'world',
        label: 'Vision Avatar Art Analyzer',
        desc: 'Inspects character portrait avatars via Vision LLM to extract appearance tags, outfit, and backdrop.',
        variables: ['Portrait Image', 'Danbooru Tags', 'JSON'],
        rows: 3,
    },

    // Prompt Studio
    {
        key: 'magic_prompt',
        category: 'generator',
        label: 'Magic Prompt Expander',
        desc: 'Expands concise user image ideas into rich, high-fidelity Danbooru tags and ComfyUI generation prompts.',
        variables: ['Input Prompt', 'Expanded Tags'],
        rows: 3,
    },

    // Character Creator
    {
        key: 'charGenDescriptionPrompt',
        category: 'chargen',
        label: 'Character Description Generator',
        desc: 'Generates rich character backstory, personality overview, and physical appearance.',
        variables: ['Draft Info'],
        rows: 2,
    },
    {
        key: 'charGenPersonalityPrompt',
        category: 'chargen',
        label: 'Character Personality Generator',
        desc: 'Expands personality traits, quirks, demeanor, psychology, and speech habits.',
        variables: ['Draft Info'],
        rows: 2,
    },
    {
        key: 'charGenScenarioPrompt',
        category: 'chargen',
        label: 'Character Scenario Generator',
        desc: 'Generates starting scenario, roleplay premise, dynamic conflict, and environment.',
        variables: ['Draft Info'],
        rows: 2,
    },
    {
        key: 'charGenFirstMesPrompt',
        category: 'chargen',
        label: 'Character First Message Generator',
        desc: 'Crafts the opening greeting message in the character’s authentic voice and setting.',
        variables: ['Draft Info'],
        rows: 2,
    },
    {
        key: 'charGenMesExamplePrompt',
        category: 'chargen',
        label: 'Message Examples Generator',
        desc: 'Creates short dialogue examples illustrating how the character speaks (<START> separated).',
        variables: ['Draft Info'],
        rows: 2,
    },
    {
        key: 'charGenSystemPromptPrompt',
        category: 'chargen',
        label: 'Character Instruction Generator',
        desc: 'Generates the custom character instruction block instructing the AI how to roleplay this persona.',
        variables: ['Draft Info'],
        rows: 2,
    },
    {
        key: 'charGenVisualTagsPrompt',
        category: 'chargen',
        label: 'Visual Tags Generator',
        desc: 'Extracts comma-separated Danbooru appearance tags for ComfyUI generation.',
        variables: ['Draft Info'],
        rows: 2,
    },
    {
        key: 'charGenEnrichPrompt',
        category: 'chargen',
        label: 'Full Profile JSON Enricher',
        desc: 'Analyzes partial character details and outputs enriched JSON filling all missing profile fields.',
        variables: ['JSON Schema'],
        rows: 2,
    },
];

export default function LLMStudio() {
    const getInitialTab = () => {
        if (typeof window !== 'undefined' && window.location?.search) {
            const params = new URLSearchParams(window.location.search);
            const t = params.get('tab');
            if (t && ['workflow', 'agents', 'library', 'gates', 'questions', 'traces', 'cluster', 'runtime', 'simulator'].includes(t)) {
                return t;
            }
        }
        return 'agents';
    };
    const [activeTab, setActiveTab] = useState(getInitialTab);

    const handleTabChange = (tab) => {
        setActiveTab(tab);
        if (typeof window !== 'undefined' && window.history?.replaceState) {
            const url = new URL(window.location.href);
            url.searchParams.set('tab', tab);
            window.history.replaceState({}, '', url.toString());
        }
    };

    const [searchQuery, setSearchQuery] = useState('');
    const [agentFilter, setAgentFilter] = useState('all');
    const [editingAgent, setEditingAgent] = useState(null);
    const [showAgentModal, setShowAgentModal] = useState(false);

    // Simulation state
    const [simMode, setSimMode] = useState('pipeline'); // 'pipeline' | 'director'
    const [simScenario, setSimScenario] = useState('I draw my enchanted frostblade and challenge the goblin warlord to a duel in the courtyard under the pouring rain!');
    const [simStage, setSimStage] = useState('all');
    const [simThreshold, setSimThreshold] = useState(0.55);
    const [simImageThreshold, setSimImageThreshold] = useState(0.65);
    const [simVariant, setSimVariant] = useState('');
    const [simResults, setSimResults] = useState(null);

    // Director Playground state
    const evalDirectorMutation = useEvaluateDirectorDecisions();
    const [directorDialogue, setDirectorDialogue] = useState(
        "User: *I step into the neon-lit alley and hand Lyra the encrypted data shard.*\nCharacter: *Lyra's eyes widen as the holographic seal flickers.* \"Wait—this is the Arasaka vault key. We need to move before the drones lock onto our signal!\""
    );
    const [directorLastSpeaker, setDirectorLastSpeaker] = useState('character');
    const [directorHasSecondary, setDirectorHasSecondary] = useState(false);

    const { confirm } = useConfirmation();

    // Queries & mutations
    const queryClient = useQueryClient();
    const { data: agentsWithVariants, isLoading: isLoadingAgents, isError: isAgentsError, error: agentsError, refetch: refetchAgents } = useAgentsWithVariants();
    // The combined endpoint returns every agent with its variants attached.
    // If it fails, fall back to the plain list so the tab still renders.
    const { data: agentsFallback = [] } = useAgents();
    const agents = agentsWithVariants ?? agentsFallback;
    const createAgentMutation = useCreateAgent();
    const updateAgentMutation = useUpdateAgent();
    const deleteAgentMutation = useDeleteAgent();
    const simulateMutation = useSimulateWorkflow();

    const { data: defaultProvider } = useLLMDefaultProvider();
    const { data: availableModels = [] } = useLLMAvailableModels();
    const { data: routing = {} } = useLLMRouting();
    const { data: runtimeDefaults } = useLLMRuntimeDefaults();
    const { data: gateRegistry } = useLLMDirectorGates();
    const catalog = useLLMCatalog();
    const setActiveModelsMutation = useSetActiveModels();

    const { providers = [] } = useProvidersPageData?.() || {};
    const llmStatus = useLLMProviderStatus?.() || { enabledProviders: [], isLoading: false };
    const setDefaultMutation = useSetLLMDefault();

    const llmProviders = useMemo(() => {
        return (providers || []).filter(p =>
            p.worker_type === 'llm' ||
            p.worker_type === 'hybrid' ||
            (Array.isArray(p.capabilities) && p.capabilities.includes('llm')) ||
            p.id?.startsWith('llm')
        );
    }, [providers]);

    const [providerId, setProviderId] = useState('');
    const [modelId, setModelId] = useState('');

    useEffect(() => {
        const resolvedDefault = llmStatus?.defaultProvider || defaultProvider;
        if (resolvedDefault) {
            setProviderId(resolvedDefault.provider_id || '');
            setModelId(resolvedDefault.model_id || '');
        }
    }, [llmStatus?.defaultProvider, defaultProvider]);

    const handleSaveDefaultProvider = async () => {
        try {
            await setDefaultMutation.mutateAsync({ provider_id: providerId, model_id: modelId });
            toast.success('Default LLM provider updated');
        } catch {
            toast.error('Failed to update LLM provider');
        }
    };

    // Global AI & Sampling state
    const globalSettings = useSettings();
    const { updateCategory } = useUpdateSettings();
    const [aiSettings, setAiSettings] = useState({
        maxContextTokens: 4096,
        temperature: 0.8,
        topP: null,
        maxOutputTokens: null,
        frequencyPenalty: null,
        presencePenalty: null,
        ttsEnabled: true,
        ragEnabled: true,
        ragMaxDistance: 0.6,
        memoryExtractionEnabled: true,
        idleSimEnabled: false,
        idleSimIntervalSeconds: 600,
    });
    const [aiSaving, setAiSaving] = useState(false);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await settingsApi.get();
                const ai = res?.settings?.ai;
                if (ai && !cancelled) {
                    setAiSettings((prev) => ({
                        ...prev,
                        maxContextTokens: ai.maxContextTokens != null ? Number(ai.maxContextTokens) : prev.maxContextTokens,
                        temperature: ai.temperature != null ? Number(ai.temperature) : prev.temperature,
                        topP: ai.top_p != null ? Number(ai.top_p) : prev.topP,
                        maxOutputTokens: ai.max_output_tokens != null ? Number(ai.max_output_tokens) : prev.maxOutputTokens,
                        frequencyPenalty: ai.frequency_penalty != null ? Number(ai.frequency_penalty) : prev.frequencyPenalty,
                        presencePenalty: ai.presence_penalty != null ? Number(ai.presence_penalty) : prev.presencePenalty,
                        ttsEnabled: ai.ttsEnabled != null ? !!ai.ttsEnabled : prev.ttsEnabled,
                        ragEnabled: ai.ragEnabled != null ? !!ai.ragEnabled : prev.ragEnabled,
                        ragMaxDistance: ai.ragMaxDistance != null ? Number(ai.ragMaxDistance) : prev.ragMaxDistance,
                        memoryExtractionEnabled: ai.memoryExtractionEnabled != null ? !!ai.memoryExtractionEnabled : prev.memoryExtractionEnabled,
                        idleSimEnabled: ai.idleSimEnabled != null ? !!ai.idleSimEnabled : prev.idleSimEnabled,
                        idleSimIntervalSeconds: ai.idleSimIntervalSeconds != null ? Number(ai.idleSimIntervalSeconds) : prev.idleSimIntervalSeconds,
                    }));
                }
            } catch {
                if (globalSettings?.ai) {
                    setAiSettings((prev) => ({ ...prev, ...globalSettings.ai }));
                }
            }
        })();
        return () => { cancelled = true; };
    }, [globalSettings?.ai]);

    const handleSaveAiSettings = async () => {
        setAiSaving(true);
        try {
            await settingsApi.update({
                ai: {
                    maxContextTokens: Number(aiSettings.maxContextTokens),
                    temperature: Number(aiSettings.temperature),
                    top_p: aiSettings.topP == null ? null : Number(aiSettings.topP),
                    max_output_tokens: aiSettings.maxOutputTokens == null ? null : Number(aiSettings.maxOutputTokens),
                    frequency_penalty: aiSettings.frequencyPenalty == null ? null : Number(aiSettings.frequencyPenalty),
                    presence_penalty: aiSettings.presencePenalty == null ? null : Number(aiSettings.presencePenalty),
                    ttsEnabled: !!aiSettings.ttsEnabled,
                    ragEnabled: aiSettings.ragEnabled !== false,
                    ragMaxDistance: Number(aiSettings.ragMaxDistance) || 0.6,
                    memoryExtractionEnabled: aiSettings.memoryExtractionEnabled !== false,
                    idleSimEnabled: !!aiSettings.idleSimEnabled,
                    idleSimIntervalSeconds: Number(aiSettings.idleSimIntervalSeconds) || 600,
                }
            });
            if (updateCategory) {
                updateCategory('ai', { ...aiSettings });
            }
            toast.success('Inference and runtime defaults saved to backend');
        } catch {
            toast.error('Failed to save AI settings');
        } finally {
            setAiSaving(false);
        }
    };

    const handleResetAiSettings = () => {
        setAiSettings({
            maxContextTokens: 4096,
            temperature: 0.8,
            topP: null,
            maxOutputTokens: null,
            frequencyPenalty: null,
            presencePenalty: null,
            ttsEnabled: true,
            ragEnabled: true,
            ragMaxDistance: 0.6,
            memoryExtractionEnabled: true,
            idleSimEnabled: false,
            idleSimIntervalSeconds: 600,
        });
        toast.success('Inference settings reset to defaults (click Save to persist)');
    };

    // System Prompts state
    const {
        data: blocksData,
        isLoading: isLoadingPrompts,
        isError: isErrorPrompts,
        error: errorPrompts,
        refetch: refetchPrompts,
    } = useQuery({
        queryKey: ['system_prompts_blocks'],
        queryFn: () => settingsApi.getSystemPrompts(),
        staleTime: 30000,
    });
    const [promptDraft, setPromptDraft] = useState({});
    const [savingPrompts, setSavingPrompts] = useState(false);
    const [promptCategoryFilter, setPromptCategoryFilter] = useState('all');
    const [promptSearch, setPromptSearch] = useState('');
    const seededDraftRef = useRef(false);

    // The user's OWN prompt blocks. The built-in ones are a fixed set the
    // code looks up by name; these are a list, so they can be added and
    // removed.
    const { data: promptLibraryData } = useQuery({
        queryKey: ['system_prompt_library'],
        queryFn: () => settingsApi.getSystemPromptLibrary(),
        staleTime: 30000,
    });
    const promptLibrary = useMemo(() => promptLibraryData?.entries || [], [promptLibraryData]);
    const [newPromptOpen, setNewPromptOpen] = useState(false);
    const [newPromptDraft, setNewPromptDraft] = useState({ key: '', label: '', category: 'Custom', prompt: '' });

    useEffect(() => {
        if (seededDraftRef.current || !blocksData?.blocks) return;
        seededDraftRef.current = true;
        setPromptDraft({ ...SYSTEM_PROMPT_DEFAULTS, ...blocksData.blocks });
    }, [blocksData]);

    const modifiedPromptCount = useMemo(() => {
        if (!blocksData?.blocks) return 0;
        return Object.keys(promptDraft).filter((k) => {
            const current = (promptDraft[k] || '').trim();
            const original = (blocksData.blocks[k] || SYSTEM_PROMPT_DEFAULTS[k] || '').trim();
            return current !== original;
        }).length;
    }, [promptDraft, blocksData]);

    const handleSavePrompts = async () => {
        setSavingPrompts(true);
        try {
            await settingsApi.updateSystemPrompts({ blocks: promptDraft });
            toast.success('System prompts updated in config.json');
            queryClient.invalidateQueries({ queryKey: ['system_prompts_blocks'] });
        } catch {
            toast.error('Failed to save system prompts');
        } finally {
            setSavingPrompts(false);
        }
    };

    const handleResetPrompt = (key) => {
        const defVal = SYSTEM_PROMPT_DEFAULTS[key] || '';
        setPromptDraft((prev) => ({ ...prev, [key]: defVal }));
        toast.success(`Reset ${key} to default`);
    };

    const handleDiscardPrompts = () => {
        if (!blocksData?.blocks) return;
        setPromptDraft({ ...SYSTEM_PROMPT_DEFAULTS, ...blocksData.blocks });
        toast.success('Discarded unsaved prompt modifications');
    };

    const handleCopyVariable = async (variableText) => {
        const ok = await copyToClipboard(variableText);
        if (ok) {
            toast.success(`Copied ${variableText} to clipboard`);
        }
    };

    // The built-in blocks and the user's own, as one list.
    //
    // The built-in ones carry their metadata from a compiled-in constant; the
    // user's own carry theirs from the API, because only the backend knows
    // what was actually stored.
    const allPromptMetadata = useMemo(() => {
        const builtin = SYSTEM_PROMPT_METADATA.map((p) => ({ ...p, custom: false }));
        const custom = promptLibrary.map((e) => ({
            key: e.key,
            label: e.label,
            category: e.category || 'Custom',
            desc: 'Your own prompt block.',
            custom: true,
        }));
        return [...builtin, ...custom];
    }, [promptLibrary]);

    const filteredPrompts = useMemo(() => {
        return allPromptMetadata.filter((p) => {
            if (promptCategoryFilter !== 'all' && p.category !== promptCategoryFilter) {
                return false;
            }
            if (!promptSearch.trim()) return true;
            const query = promptSearch.toLowerCase();
            return (
                p.label.toLowerCase().includes(query) ||
                p.key.toLowerCase().includes(query) ||
                (p.desc || '').toLowerCase().includes(query) ||
                (promptDraft[p.key] || '').toLowerCase().includes(query)
            );
        });
    }, [allPromptMetadata, promptCategoryFilter, promptSearch, promptDraft]);

    const handleAddPrompt = async () => {
        const key = (newPromptDraft.key || '').trim();
        if (!key || !newPromptDraft.prompt.trim()) {
            toast.error('A prompt block needs a key and a prompt.');
            return;
        }
        try {
            await settingsApi.createSystemPromptLibraryEntry({
                key,
                label: newPromptDraft.label.trim() || key,
                category: newPromptDraft.category.trim() || 'Custom',
                prompt: newPromptDraft.prompt.trim(),
            });
            toast.success(`Added prompt block "${key}".`);
            setNewPromptOpen(false);
            setNewPromptDraft({ key: '', label: '', category: 'Custom', prompt: '' });
            queryClient.invalidateQueries({ queryKey: ['system_prompt_library'] });
            queryClient.invalidateQueries({ queryKey: ['system_prompts_blocks'] });
        } catch (err) {
            toast.error(err?.message || 'Could not add the prompt block.');
        }
    };

    const handleRemovePrompt = async (entry) => {
        try {
            await settingsApi.deleteSystemPromptLibraryEntry(entry.key);
            toast.success(`Removed prompt block "${entry.key}".`);
            setPromptDraft((prev) => {
                const next = { ...prev };
                delete next[entry.key];
                return next;
            });
            queryClient.invalidateQueries({ queryKey: ['system_prompt_library'] });
            queryClient.invalidateQueries({ queryKey: ['system_prompts_blocks'] });
        } catch (err) {
            toast.error(err?.message || 'Could not remove the prompt block.');
        }
    };

    const handleSavePromptLibraryEntry = async (entry) => {
        const value = (promptDraft[entry.key] || '').trim();
        if (!value || value === (entry.prompt || '').trim()) return;
        try {
            await settingsApi.updateSystemPromptLibraryEntry(entry.key, {
                key: entry.key,
                label: entry.label,
                category: entry.category,
                prompt: value,
            });
            toast.success(`Saved "${entry.key}".`);
            queryClient.invalidateQueries({ queryKey: ['system_prompt_library'] });
            queryClient.invalidateQueries({ queryKey: ['system_prompts_blocks'] });
        } catch (err) {
            toast.error(err?.message || 'Could not save the prompt block.');
        }
    };

    const handleRunDirectorEval = () => {
        const lines = directorDialogue.split('\n').filter(Boolean);
        const recent_messages = lines.map((line) => {
            if (line.toLowerCase().startsWith('user:')) {
                return { role: 'user', content: line.slice(5).trim() };
            }
            if (line.toLowerCase().startsWith('narrator:')) {
                return { role: 'system', content: line.slice(9).trim() };
            }
            const cleaned = line.toLowerCase().startsWith('character:') ? line.slice(10).trim() : line.trim();
            return { role: 'assistant', content: cleaned };
        });

        evalDirectorMutation.mutate({
            recent_messages,
            character_name: 'Lyra',
            scenario: 'Cyberpunk infiltration in Neo-Veridia.',
            has_secondary_character: directorHasSecondary,
            last_speaker: directorLastSpeaker,
            chain_depth: 0,
            state_snapshot: {
                story_location: 'Sector 7 Neon Alley',
                story_time: 'Midnight, Heavy Rain',
                character_mood: 'Alert',
            },
        });
    };

    const gateCategories = useMemo(() => {
        const categories = gateRegistry?.categories;
        if (Array.isArray(categories) && categories.length > 0) {
            return categories.map((category) => ({
                ...category,
                ...(GATE_CATEGORY_STYLES[category.id] || {}),
            }));
        }
        return FALLBACK_GATE_CATEGORIES;
    }, [gateRegistry]);

    const gateThreshold = runtimeDefaults?.gate_threshold ?? gateRegistry?.threshold ?? 0.55;

    // Filtered agents
    //
    // The list comes from the combined endpoint, which returns every agent
    // together with its variants and its resolved active variant. The tab
    // used to load the list and then fetch each agent's variants separately —
    // one request per agent — which the backend already had a single
    // response for.
    const filteredAgents = useMemo(() => {
        return agents.filter(agent => {
            const matchesSearch = agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            agent.slug.toLowerCase().includes(searchQuery.toLowerCase()) ||
            (agent.description && agent.description.toLowerCase().includes(searchQuery.toLowerCase()));
            const matchesType = agentFilter === 'all' || agent.agent_type === agentFilter;
            return matchesSearch && matchesType;
        });
    }, [agents, searchQuery, agentFilter]);

    // Delete custom agent handler
    const handleDeleteAgent = (agent) => {
        if (agent.is_builtin) {
            toast.error('Built-in system agents cannot be deleted.');
            return;
        }
        confirm({
            title: `Delete Agent "${agent.name}"?`,
            message: `Are you sure you want to delete the custom agent "${agent.slug}"? Laya will no longer be able to route turns to this agent profile.`,
            confirmLabel: 'Delete Agent',
            confirmTone: 'danger',
            onConfirm: async () => {
                try {
                    await deleteAgentMutation.mutateAsync(agent.id);
                    toast.success(`Agent "${agent.name}" deleted.`);
                } catch (err) {
                    toast.error(`Failed to delete agent: ${err.message}`);
                }
            }
        });
    };

    // Run simulation handler
    const handleRunSimulation = async () => {
        if (!simScenario.trim()) {
            toast.error('Please enter a scenario prompt to simulate.');
            return;
        }
        try {
            const result = await simulateMutation.mutateAsync({
                prompt: simScenario,
                stage: simStage,
                state_snapshot: {
                    gate_threshold: simThreshold,
                    image_threshold: simImageThreshold,
                },
                ...(simVariant.trim() ? { variant_slug: simVariant.trim() } : {}),
            });
            setSimResults(result);
            toast.success('Simulation completed successfully!');
        } catch {
            // Handled by hook error toast
        }
    };

    return (
        <div className="flex-1 min-h-0 flex flex-col bg-[#0B0E14] text-gray-100 overflow-y-auto custom-scrollbar p-4 md:p-8">
            {/* Page Header */}
            <div className="max-w-7xl w-full mx-auto space-y-6">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/5">
                    {/* The title column is capped, not free.

                    It used to be an unconstrained flex child, so the tab strip
                    could take the whole row and leave the title a column two
                    characters wide — "LLM / Studio & / Multi- / Agent /
                    Workflow" — with the subtitle under it in a 140px ribbon.
                    The cap gives the title its natural width and hands the
                    rest of the row to the tabs, which then scroll.
                    */}
                    <div className="min-w-0 md:max-w-lg">
                        <div className="flex items-center gap-2.5">
                            <span className="shrink-0 p-2 rounded-xl bg-gradient-to-tr from-blue-600/20 to-purple-600/20 border border-blue-500/30 text-blue-400">
                                <Cpu size={22} />
                            </span>
                            <div className="min-w-0">
                                <h1 className="text-2xl font-bold tracking-tight text-white">
                                    <span className="truncate block">LLM Studio &amp; Multi-Agent Workflow</span>
                                </h1>
                                <p className="text-xs text-gray-400">
                                    Manage modular agents, 16-gate Statekeeper thresholds, model cluster routing, and workflow pipeline execution.
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* Navigation Tabs

                    `shrink-0` and `overflow-x-auto` were on the same element,
                    and `shrink-0` won: the strip refused to give up any
                    width, so it kept its full intrinsic width, overflowed the
                    page, and the last tab was cut off with no way to reach
                    it. The `overflow-x-auto` was there to scroll and never
                    could.

                    It scrolls now — but a strip with five of its nine tabs
                    hidden behind a scroll is a strip nobody can find
                    anything on, so it wraps instead. Every tab is on the
                    page, and the page never scrolls sideways.
                    */}
                    <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-xl bg-gray-900/80 border border-white/10 min-w-0 flex-1">
                        <button
                            type="button"
                            onClick={() => handleTabChange('workflow')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'workflow' ? "bg-blue-600 text-white shadow-md shadow-blue-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <GitBranch size={14} />
                            <span>Workflow</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('agents')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'agents' ? "bg-indigo-600 text-white shadow-md shadow-indigo-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <Bot size={14} />
                            <span>Agent Studio ({agents.length})</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('library')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'library' ? "bg-fuchsia-600 text-white shadow-md shadow-fuchsia-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <Library size={14} />
                            <span>Prompt Library</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('gates')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'gates' ? "bg-purple-600 text-white shadow-md shadow-purple-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <Shield size={14} />
                            <span>16-Gate Studio</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('questions')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'questions' ? "bg-pink-600 text-white shadow-md shadow-pink-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <HelpCircle size={14} />
                            <span>Laya Questions</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('traces')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'traces' ? "bg-cyan-600 text-white shadow-md shadow-cyan-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <Activity size={14} />
                            <span>Decision Traces</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('cluster')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'cluster' ? "bg-emerald-600 text-white shadow-md shadow-emerald-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <Server size={14} />
                            <span>Model Cluster</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('runtime')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'runtime' ? "bg-teal-600 text-white shadow-md shadow-teal-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <Sliders size={14} />
                            <span>Inference &amp; Runtime</span>
                        </button>
                        <button
                            type="button"
                            onClick={() => handleTabChange('simulator')}
                            className={clsx(
                                "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shrink-0",
                                activeTab === 'simulator' ? "bg-amber-600 text-white shadow-md shadow-amber-500/20" : "text-gray-400 hover:text-gray-200 hover:bg-white/5"
                            )}
                        >
                            <Play size={14} />
                            <span>Workflow Simulator</span>
                        </button>
                    </div>
                </div>

                {/* Tab 0: Workflow Pipeline */}
                {activeTab === 'workflow' && <WorkflowTab />}

                {/* Tab: Laya Questions */}
                {activeTab === 'library' && <PromptLibraryTab agents={agents} />}
                {activeTab === 'questions' && <LayaQuestionsTab />}

                {/* Tab: Decision Traces */}
                {activeTab === 'traces' && <DecisionTraceTab />}

                {/* Tab 1: Agent Studio */}
                {activeTab === 'agents' && (
                    <div className="space-y-6">
                        {/* Control Bar */}
                        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
                            <div className="flex flex-1 items-center gap-2 max-w-md">
                                <div className="relative flex-1">
                                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                    <input
                                        type="text"
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        placeholder="Search agents by name, slug, or routing description..."
                                        className="w-full pl-9 pr-3 py-1.5 rounded-xl bg-gray-900/80 border border-white/10 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                                    />
                                </div>
                                <select
                                    value={agentFilter}
                                    onChange={(e) => setAgentFilter(e.target.value)}
                                    className="bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-300 focus:outline-none focus:border-blue-500/50"
                                >
                                    <option value="all">All Types</option>
                                    <option value="character">Character</option>
                                    <option value="narrator">Narrator</option>
                                    <option value="specialist">Specialist</option>
                                </select>
                            </div>

                            <button
                                type="button"
                                onClick={() => {
                                    setEditingAgent(null);
                                    setShowAgentModal(true);
                                }}
                                className="flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 transition-all"
                            >
                                <Plus size={14} />
                                <span>Create Custom Agent</span>
                            </button>
                        </div>

                        {/* Agents Grid */}
                        {isLoadingAgents ? (
                            <div className="p-12 text-center text-gray-400 text-xs">
                                <RefreshCw size={24} className="animate-spin mx-auto mb-2 text-blue-400" />
                                Loading registered agents...
                            </div>
                        ) : isAgentsError ? (
                            <QueryErrorState error={agentsError} onRetry={refetchAgents} />
                        ) : filteredAgents.length === 0 ? (
                            <div className="glass-panel p-8 rounded-2xl text-center text-gray-400 text-xs space-y-2 border border-white/5">
                                <Bot size={32} className="mx-auto text-gray-600 mb-2" />
                                <div className="font-semibold text-gray-300">No agents found</div>
                                <p className="text-gray-500 max-w-sm mx-auto">
                                    {searchQuery ? `No agents match "${searchQuery}".` : 'No registered agent profiles found.'}
                                </p>
                            </div>
                        ) : (
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                                {filteredAgents.map((agent) => (
                                    <div
                                        key={agent.id}
                                        className={clsx(
                                            "glass-panel rounded-2xl p-5 border transition-all flex flex-col justify-between group",
                                            agent.is_builtin ? "border-white/10 bg-gray-900/40" : "border-blue-500/20 bg-blue-950/5 hover:border-blue-500/40"
                                        )}
                                    >
                                        <div className="space-y-3">
                                            <div className="flex items-start justify-between gap-2">
                                                <div>
                                                    <div className="flex items-center gap-2">
                                                        <h3 className="font-bold text-sm text-white group-hover:text-blue-300 transition-colors">
                                                            {agent.name}
                                                        </h3>
                                                        {agent.is_builtin ? (
                                                            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-800 border border-white/10 text-3xs font-semibold text-gray-400 uppercase">
                                                                <Lock size={9} /> Built-in
                                                            </span>
                                                        ) : (
                                                            <span className="px-2 py-0.5 rounded-full bg-blue-500/15 border border-blue-500/30 text-3xs font-semibold text-blue-300 uppercase">
                                                                Custom
                                                            </span>
                                                        )}
                                                    </div>
                                                    <div className="font-mono text-3xs text-gray-500 mt-0.5">
                                                        slug: <span className="text-gray-300 font-bold">{agent.slug}</span> · type: <span className="text-blue-300">{agent.agent_type}</span>
                                                    </div>
                                                </div>

                                                <span className={clsx(
                                                    "w-2.5 h-2.5 rounded-full mt-1 shrink-0",
                                                    agent.enabled ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]" : "bg-gray-600"
                                                )} title={agent.enabled ? "Active" : "Disabled"} />
                                            </div>

                                            <p className="text-xs text-gray-400 line-clamp-3 leading-relaxed">
                                                {agent.description || 'No routing description provided.'}
                                            </p>

                                            <div className="pt-2 border-t border-white/5 space-y-1.5 text-3xs text-gray-400">
                                                <div className="flex justify-between items-center">
                                                    <span>Target Engine:</span>
                                                    <span className={clsx("px-1.5 py-0.5 rounded font-mono font-bold uppercase", agent.model_target === 'util' ? 'bg-purple-500/15 text-purple-300' : 'bg-blue-500/15 text-blue-300')}>
                                                        {agent.model_target || 'rp'}
                                                    </span>
                                                </div>
                                                {agent.model_override && (
                                                    <div className="flex justify-between items-center">
                                                        <span>Model Override:</span>
                                                        <span className="font-mono text-gray-300 truncate max-w-[150px]">{agent.model_override}</span>
                                                    </div>
                                                )}
                                                <div className="grid grid-cols-[auto_1fr] items-center gap-2">
                                                    <span className="shrink-0">Sampling:</span>
                                                    <span className="font-mono text-gray-400 text-right whitespace-nowrap overflow-hidden text-ellipsis">
                                                        T: {agent.temperature ?? 'def'} · P: {agent.top_p ?? 'def'} · Max: {agent.max_tokens ?? 'def'}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>

                                        <div className="mt-4 pt-3 border-t border-white/5 flex items-center justify-between gap-2">
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setEditingAgent(agent);
                                                    setShowAgentModal(true);
                                                }}
                                                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-medium transition-colors"
                                            >
                                                <Edit2 size={12} />
                                                <span>{agent.is_builtin ? 'View Profile' : 'Edit'}</span>
                                            </button>

                                            {!agent.is_builtin && (
                                                <button
                                                    type="button"
                                                    onClick={() => handleDeleteAgent(agent)}
                                                    className="p-1.5 rounded-lg text-gray-500 hover:text-rose-400 hover:bg-rose-500/10 transition-colors"
                                                    title="Delete custom agent"
                                                >
                                                    <Trash2 size={14} />
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}

                {/* Tab 2: 16-Gate Statekeeper Studio */}
                {activeTab === 'gates' && (
                    <div className="space-y-6">
                        {/* Explanatory Banner */}
                        <div className="glass-panel p-5 rounded-2xl border border-purple-500/20 bg-purple-950/10 space-y-2">
                            <div className="flex items-center gap-2">
                                <Shield size={18} className="text-purple-400" />
                                <h3 className="font-bold text-sm text-purple-200">
                                    System 1 Classification vs. System 2 State Update Architecture
                                </h3>
                            </div>
                            <p className="text-xs text-purple-200/80 leading-relaxed">
                                Laya acts as the microsecond <strong>Entailment Classifier</strong> evaluating 16 discrete gate questions.
                                Crucially, Laya never mutates story data directly. When one or more gates cross the activation threshold,
                                only the passed fields are synthesized into a targeted JSON schema and dispatched to the <strong>Updater Agent</strong> running
                                on the expressive Util LLM (e.g. Gemma 3 12B). This prevents state hallucination while guaranteeing comprehensive world tracking.
                            </p>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-3xs font-mono text-purple-300/80 pt-1">
                                <span>Activation threshold: {Math.round(gateThreshold * 100)}%</span>
                                <span>Completion bands: {Math.round((gateRegistry?.completion_bands?.uncertain_low ?? 0.4) * 100)}%–{Math.round((gateRegistry?.completion_bands?.uncertain_high ?? 0.6) * 100)}%</span>
                                <span>{gateCategories.reduce((sum, category) => sum + category.gates.length, 0)} gates</span>
                            </div>
                        </div>

                        {/* Gate Categories Grid */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                            {gateCategories.map((category) => {
                                const IconComponent = category.icon;
                                return (
                                    <div
                                        key={category.id}
                                        className={clsx("glass-panel p-5 rounded-2xl border space-y-3", category.color)}
                                    >
                                        <div className="flex items-center gap-2 pb-2 border-b border-white/5">
                                            <IconComponent size={16} />
                                            <h4 className="font-bold text-xs uppercase tracking-wider text-white">
                                                {category.title}
                                            </h4>
                                            <span className="ml-auto text-3xs font-mono font-bold text-gray-400">
                                                {category.gates.length} Gates
                                            </span>
                                        </div>

                                        <div className="space-y-2">
                                            {category.gates.map((gate) => (
                                                <div
                                                    key={gate.key}
                                                    className="p-3 rounded-xl bg-gray-900/60 border border-white/5 space-y-1 hover:border-white/10 transition-colors"
                                                >
                                                    <div className="flex items-center justify-between text-xs">
                                                        <span className="font-semibold text-gray-200">{gate.label}</span>
                                                        <span className="font-mono text-3xs text-gray-500">{gate.key}</span>
                                                    </div>
                                                    <p className="text-3xs text-gray-400 leading-normal">
                                                        {gate.description}
                                                    </p>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}

                {/* Tab 3: Model Cluster & Routing */}
                {activeTab === 'cluster' && (
                    <div className="space-y-6">
                        {/* Worker Status & Default Provider Row */}
                        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
                            {/* LLM Worker Status */}
                            <div className="lg:col-span-5 glass-panel p-5 rounded-2xl border border-white/10 space-y-3">
                                <div className="flex items-center justify-between pb-2 border-b border-white/5">
                                    <div className="flex items-center gap-2">
                                        <Brain size={16} className="text-purple-400" />
                                        <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                                            LLM Worker Status
                                        </h3>
                                    </div>
                                    {llmStatus.isLoading ? (
                                        <Loader2 size={14} className="animate-spin text-blue-400" />
                                    ) : llmStatus.isHealthy ? (
                                        <div className="flex items-center gap-1.5 text-emerald-400 text-xs font-bold">
                                            <CheckCircle size={14} />
                                            <span>Connected</span>
                                        </div>
                                    ) : (
                                        <div className="flex items-center gap-1.5 text-rose-400 text-xs font-bold">
                                            <XCircle size={14} />
                                            <span>Unavailable</span>
                                        </div>
                                    )}
                                </div>
                                <p className="text-3xs text-gray-400 leading-normal">
                                    Live connection status and model availability across active cloud/local LLM providers.
                                </p>
                                {llmStatus.enabledProviders?.length === 0 ? (
                                    <div className="text-3xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-xl p-3">
                                        No LLM providers configured. Add or enable one in <strong>Providers</strong> to unlock chat and generation.
                                    </div>
                                ) : (
                                    <div className="space-y-1.5 pt-1">
                                        <div className="text-3xs font-semibold uppercase tracking-wider text-gray-500">
                                            Enabled Providers ({llmStatus.enabledProviders?.length || 0})
                                        </div>
                                        <div className="flex flex-wrap gap-1.5">
                                            {llmStatus.enabledProviders?.map(p => (
                                                <span key={p.provider_id} className="px-2 py-0.5 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-300 text-3xs font-mono font-semibold flex items-center gap-1">
                                                    <Server size={9} />
                                                    {p.provider_id}
                                                    {p.is_default && <span className="bg-purple-400/20 text-purple-200 px-1 py-0.2 rounded text-3xs font-bold">DEFAULT</span>}
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Default Provider & Model Form */}
                            <div className="lg:col-span-7 glass-panel p-5 rounded-2xl border border-white/10 space-y-3">
                                <div className="flex items-center justify-between pb-2 border-b border-white/5">
                                    <div>
                                        <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                                            Default LLM Provider &amp; Model
                                        </h3>
                                        <p className="text-3xs text-gray-400">
                                            Fallback provider and model target for conversational turns without overrides.
                                        </p>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={handleSaveDefaultProvider}
                                        disabled={setDefaultMutation.isPending}
                                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-md shadow-blue-500/20 transition-all disabled:opacity-50"
                                    >
                                        {setDefaultMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                                        <span>Save Default</span>
                                    </button>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                                    <div>
                                        <label htmlFor="llm-default-provider-input" className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                            Provider
                                        </label>
                                        <select
                                            id="llm-default-provider-input"
                                            value={providerId}
                                            onChange={(e) => setProviderId(e.target.value)}
                                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                                        >
                                            <option value="">Auto-detect</option>
                                            {llmProviders.map(p => (
                                                <option key={p.id} value={p.id}>{p.id}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label htmlFor="llm-default-model-input" className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                            Model ID (Optional)
                                            {llmStatus.isModelsLoading && <Loader2 size={10} className="inline ml-1 animate-spin" />}
                                        </label>
                                        <select
                                            id="llm-default-model-input"
                                            value={modelId}
                                            onChange={(e) => setModelId(e.target.value)}
                                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                                            disabled={llmStatus.isModelsLoading}
                                        >
                                            <option value="">Default Model</option>
                                            {availableModels.map(m => (
                                                <option key={m.id || m} value={m.id || m}>{m.name || m.id || m}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Interactive Model Routing Cards (3 Roles) */}
                        <div className="space-y-4">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                                        Active Model Routing
                                    </h3>
                                    <p className="text-3xs text-gray-400">
                                        Dispatch roleplay prose, structured world updates, and zero-VRAM director classification to their specialized engines.
                                    </p>
                                </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                                {['rp', 'util', 'decisions'].map((role) => {
                                    const info = routing?.roles?.[role] || {};
                                    const currentActive = role === 'rp'
                                        ? (catalog.data?.active?.rp || info.active || info.primary)
                                        : role === 'util'
                                            ? (catalog.data?.active?.util || info.active || info.primary)
                                            : (catalog.data?.active?.decisions || info.active || info.primary || 'laya_english');

                                    const isRp = role === 'rp';
                                    const isUtil = role === 'util';
                                    const isDecisions = role === 'decisions';

                                    const roleTitle = isRp ? 'Roleplay Engine (RP)' : isUtil ? 'Utility Engine (Util)' : 'Director Classifier (Laya)';
                                    const roleDesc = isRp
                                        ? 'Dedicated to rich character dialogue, multi-turn roleplay prose, emotional depth, and narrative scene continuity.'
                                        : isUtil
                                            ? 'Powers the Statekeeper Updater agent, JSON delta patches, episodic memory compilation, and fast-travel world ticks.'
                                            : 'Zero-VRAM CPU/ONNX semantic NLI classifier for instant turn routing, Fate & Skill checks, and 16-gate Statekeeper triggering.';

                                    const cardBorder = isRp ? 'border-blue-500/20 bg-blue-950/5' : isUtil ? 'border-purple-500/20 bg-purple-950/5' : 'border-emerald-500/20 bg-emerald-950/5';
                                    const IconComponent = isRp ? Bot : isUtil ? Zap : Brain;
                                    const iconColor = isRp ? 'text-blue-400' : isUtil ? 'text-purple-400' : 'text-emerald-400';

                                    return (
                                        <div key={role} className={clsx("glass-panel p-5 rounded-2xl border space-y-3 flex flex-col justify-between", cardBorder)}>
                                            <div className="space-y-3">
                                                <div className="flex items-center justify-between pb-2 border-b border-white/5">
                                                    <div className="flex items-center gap-2">
                                                        <IconComponent size={16} className={iconColor} />
                                                        <h4 className="font-bold text-xs uppercase tracking-wider text-white">
                                                            {roleTitle}
                                                        </h4>
                                                    </div>
                                                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                                                </div>

                                                <p className="text-3xs text-gray-400 leading-normal">
                                                    {roleDesc}
                                                </p>

                                                {isDecisions && (
                                                    <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/25 text-3xs font-semibold text-emerald-300">
                                                        <span>🧠 System 1 CPU / RAM</span>
                                                        <span>•</span>
                                                        <span>0 MB GPU VRAM</span>
                                                    </div>
                                                )}

                                                <div className="space-y-1">
                                                    <label htmlFor={`active-model-${role}`} className="text-3xs font-semibold uppercase tracking-wider text-gray-400 block">
                                                        Active Model
                                                    </label>
                                                    <select
                                                        id={`active-model-${role}`}
                                                        aria-label={`Active ${role} model`}
                                                        value={currentActive || ''}
                                                        onChange={(e) => {
                                                            const val = e.target.value;
                                                            const activeRp = isRp ? val : (catalog.data?.active?.rp || routing?.roles?.rp?.primary);
                                                            const activeUtil = isUtil ? val : (catalog.data?.active?.util || routing?.roles?.util?.primary);
                                                            const activeDecisions = isDecisions ? val : (catalog.data?.active?.decisions || routing?.roles?.decisions?.primary || 'laya_english');
                                                            setActiveModelsMutation.mutate({
                                                                active_rp: activeRp,
                                                                active_util: activeUtil,
                                                                active_decisions: activeDecisions,
                                                            });
                                                        }}
                                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                                                        disabled={setActiveModelsMutation.isPending}
                                                    >
                                                        {isUtil && (
                                                            <option value="same_as_rp">⚡ Same as RP Model (Unified VRAM / Faster)</option>
                                                        )}
                                                        {isDecisions && (
                                                            <>
                                                                <option value="same_as_util">🔄 Fallback: Use Util LLM (JSON Schema)</option>
                                                                <option value="disabled">⏸️ Disabled (Direct Turn / No Director)</option>
                                                            </>
                                                        )}
                                                        {info.chain?.map((mid) => {
                                                            const modelMeta = catalog.data?.catalog?.[mid];
                                                            const badges = [];
                                                            if (modelMeta?.engine_type === 'system1_laya') badges.push('🧠 CPU/RAM');
                                                            if (modelMeta?.has_vision) badges.push('👁️ Vision');
                                                            if (mid.includes('a4b')) badges.push('⚡ Fast MoE');
                                                            if (mid.includes('q4')) badges.push('Q4');
                                                            const badgeStr = badges.length > 0 ? ` (${badges.join(', ')})` : '';
                                                            return (
                                                                <option key={mid} value={mid}>{mid}{badgeStr}</option>
                                                            );
                                                        })}
                                                    </select>
                                                </div>

                                                {/* Role Explanations */}
                                                {isUtil && currentActive === 'same_as_rp' ? (
                                                    <div className="text-3xs text-blue-400/90 italic">
                                                        ⚡ Using active RP weights with temperature 0.3 for Statekeeper updates.
                                                    </div>
                                                ) : isDecisions && currentActive === 'same_as_util' ? (
                                                    <div className="text-3xs text-purple-300/90 italic">
                                                        🔄 Evaluating Director decisions via structured JSON on the active Util model.
                                                    </div>
                                                ) : isDecisions && currentActive === 'disabled' ? (
                                                    <div className="text-3xs text-gray-500 italic">
                                                        ⏸️ Director evaluation bypassed globally; turns go directly to the selected character.
                                                    </div>
                                                ) : catalog.data?.catalog?.[currentActive]?.note ? (
                                                    <div className="text-3xs text-gray-400/90 italic">
                                                        {catalog.data.catalog[currentActive].note}
                                                    </div>
                                                ) : null}
                                            </div>

                                            {/* Fallback chain badges */}
                                            {(info.chain?.length || 0) > 1 && (
                                                <div className="pt-2 border-t border-white/5 space-y-1">
                                                    <div className="text-3xs uppercase tracking-wider text-gray-500">
                                                        Fallback Chain
                                                    </div>
                                                    <div className="flex flex-wrap gap-1">
                                                        {info.chain.map((id) => (
                                                            <span
                                                                key={id}
                                                                className={clsx(
                                                                    "px-1.5 py-0.5 rounded text-3xs font-mono",
                                                                    id === currentActive
                                                                        ? (isDecisions ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-bold" : "bg-blue-500/20 text-blue-300 border border-blue-500/30 font-bold")
                                                                        : "bg-white/5 border border-white/10 text-gray-400"
                                                                )}
                                                            >
                                                                {id}
                                                            </span>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>

                            {/* Unified VRAM Mode Banner */}
                            {(routing?.shared_weights || catalog.data?.active?.util === 'same_as_rp') && (
                                <div className="px-4 py-2.5 rounded-xl bg-blue-500/10 border border-blue-500/20 text-xs text-blue-300 flex items-center gap-2">
                                    <Zap size={15} className="shrink-0 text-blue-400" />
                                    <span>
                                        <b>Unified VRAM Mode Active:</b> RP and Utility tasks share identical GPU weights, while the System 1 Decision Maker runs on CPU/RAM (0 MB GPU VRAM).
                                    </span>
                                </div>
                            )}

                            {/* Which job kinds use which role Accordion */}
                            <details className="group glass-panel p-4 rounded-xl border border-white/5">
                                <summary className="cursor-pointer text-xs font-bold uppercase tracking-widest text-gray-400 hover:text-gray-200 flex items-center justify-between list-none">
                                    <span>Which job kinds use which role</span>
                                    <ChevronDown size={14} className="text-gray-400 transition-transform group-open:rotate-180" />
                                </summary>
                                <div className="mt-3 grid gap-2 sm:grid-cols-2 pt-2 border-t border-white/5">
                                    {Object.entries(routing?.kinds || {}).map(([kind, role]) => (
                                        <div key={kind} className="flex items-center justify-between text-xs py-1 px-2 rounded bg-black/20">
                                            <span className="font-mono text-gray-300">{kind}</span>
                                            <span className={clsx("font-bold uppercase text-3xs", role === 'rp' ? 'text-blue-300' : role === 'decisions' ? 'text-emerald-300' : 'text-purple-300')}>
                                                {role}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </details>
                        </div>
                    </div>
                )}

                {/* Tab 4: Inference & Runtime */}
                {activeTab === 'runtime' && (
                    <div className="space-y-6">
                        {/* Action Header */}
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/5">
                            <div>
                                <h3 className="font-bold text-sm text-white flex items-center gap-2">
                                    <Sliders size={16} className="text-cyan-400" />
                                    <span>Inference, Sampling &amp; Memory Defaults</span>
                                </h3>
                                <p className="text-3xs text-gray-400">
                                    Global context token limits, sampler parameters, autobiographical RAG, and system prompt templates.
                                </p>
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    type="button"
                                    onClick={handleResetAiSettings}
                                    className="px-3.5 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-gray-300 text-xs font-semibold flex items-center gap-1.5 transition-all"
                                >
                                    <RotateCcw size={13} />
                                    <span>Reset</span>
                                </button>
                                <button
                                    type="button"
                                    onClick={handleSaveAiSettings}
                                    disabled={aiSaving}
                                    className="px-4 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-md shadow-cyan-500/20 flex items-center gap-1.5 transition-all disabled:opacity-50"
                                >
                                    {aiSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                                    <span>Save Settings</span>
                                </button>
                            </div>
                        </div>

                        {/* 2-Column Controls */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                            {/* Column 1: Context & Sampling */}
                            <div className="glass-panel p-5 rounded-2xl border border-white/10 space-y-4">
                                <h4 className="font-bold text-xs uppercase tracking-wider text-white border-b border-white/5 pb-2">
                                    Context Window &amp; Sampling
                                </h4>

                                {/* Max Context Tokens */}
                                <div className="space-y-1.5">
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="font-semibold text-gray-300">Max Context Tokens</span>
                                        <span className="font-mono text-cyan-300 font-bold">
                                            {aiSettings.maxContextTokens.toLocaleString()} tokens
                                        </span>
                                    </div>
                                    <input
                                        type="range"
                                        min="1024"
                                        max="32768"
                                        step="1024"
                                        value={aiSettings.maxContextTokens}
                                        onChange={(e) => setAiSettings({ ...aiSettings, maxContextTokens: parseInt(e.target.value, 10) })}
                                        className="w-full accent-cyan-500"
                                    />
                                    <p className="text-3xs text-gray-500">
                                        Maximum tokens retained in history before pruning older context turns.
                                    </p>
                                </div>

                                {/* Temperature */}
                                <div className="space-y-1.5 pt-2 border-t border-white/5">
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="font-semibold text-gray-300">Temperature</span>
                                        <span className="font-mono text-purple-300 font-bold">
                                            {Number(aiSettings.temperature).toFixed(1)}
                                        </span>
                                    </div>
                                    <input
                                        type="range"
                                        min="0.0"
                                        max="2.0"
                                        step="0.1"
                                        value={aiSettings.temperature}
                                        onChange={(e) => setAiSettings({ ...aiSettings, temperature: parseFloat(e.target.value) })}
                                        className="w-full accent-purple-500"
                                    />
                                    <div className="flex justify-between text-3xs text-gray-500 font-mono">
                                        <span>0.0 (Deterministic)</span>
                                        <span>0.8 (Creative Roleplay)</span>
                                        <span>2.0 (Wild)</span>
                                    </div>
                                </div>

                                {/* Fine Sampling Controls */}
                                <div className="pt-2 border-t border-white/5 space-y-2">
                                    <div className="text-3xs font-semibold uppercase tracking-wider text-gray-400">
                                        Sampler Penalties &amp; Cutoffs
                                    </div>
                                    <div className="grid grid-cols-2 gap-3">
                                        <div>
                                            <label className="text-3xs text-gray-400 block mb-1">Top P</label>
                                            <input
                                                type="number"
                                                min="0.0"
                                                max="1.0"
                                                step="0.05"
                                                placeholder="1.0 (Default)"
                                                value={aiSettings.topP ?? ''}
                                                onChange={(e) => setAiSettings({ ...aiSettings, topP: e.target.value === '' ? null : parseFloat(e.target.value) })}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-500 font-mono"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-3xs text-gray-400 block mb-1">Max Output Tokens</label>
                                            <input
                                                type="number"
                                                min="16"
                                                max="32768"
                                                step="16"
                                                placeholder="2048 (Default)"
                                                value={aiSettings.maxOutputTokens ?? ''}
                                                onChange={(e) => setAiSettings({ ...aiSettings, maxOutputTokens: e.target.value === '' ? null : parseInt(e.target.value, 10) })}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-500 font-mono"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-3xs text-gray-400 block mb-1">Frequency Penalty</label>
                                            <input
                                                type="number"
                                                min="-2.0"
                                                max="2.0"
                                                step="0.1"
                                                placeholder="0.0 (Default)"
                                                value={aiSettings.frequencyPenalty ?? ''}
                                                onChange={(e) => setAiSettings({ ...aiSettings, frequencyPenalty: e.target.value === '' ? null : parseFloat(e.target.value) })}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-500 font-mono"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-3xs text-gray-400 block mb-1">Presence Penalty</label>
                                            <input
                                                type="number"
                                                min="-2.0"
                                                max="2.0"
                                                step="0.1"
                                                placeholder="0.0 (Default)"
                                                value={aiSettings.presencePenalty ?? ''}
                                                onChange={(e) => setAiSettings({ ...aiSettings, presencePenalty: e.target.value === '' ? null : parseFloat(e.target.value) })}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-2.5 py-1 text-xs text-white focus:outline-none focus:border-cyan-500 font-mono"
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Column 2: Memory & Autonomous Features */}
                            <div className="glass-panel p-5 rounded-2xl border border-white/10 space-y-4">
                                <h4 className="font-bold text-xs uppercase tracking-wider text-white border-b border-white/5 pb-2">
                                    Autobiographical Memory &amp; Autonomous Intelligence
                                </h4>

                                {/* TTS Toggle */}
                                <div className="flex items-center justify-between pb-3 border-b border-white/5">
                                    <div>
                                        <div className="text-xs font-semibold text-gray-200">Text-to-Speech (TTS)</div>
                                        <div className="text-3xs text-gray-400">Generate voice narration for character chat messages</div>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setAiSettings({ ...aiSettings, ttsEnabled: !aiSettings.ttsEnabled })}
                                        className={clsx(
                                            "px-3 py-1 rounded-lg text-3xs font-bold uppercase transition-all",
                                            aiSettings.ttsEnabled ? "bg-emerald-500/20 border border-emerald-500/30 text-emerald-300" : "bg-gray-800 text-gray-500"
                                        )}
                                    >
                                        {aiSettings.ttsEnabled ? 'On' : 'Off'}
                                    </button>
                                </div>

                                {/* RAG Toggle & Distance */}
                                <div className="space-y-2 pb-3 border-b border-white/5">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <div className="text-xs font-semibold text-gray-200">Autobiographical Memory (RAG)</div>
                                            <div className="text-3xs text-gray-400">Semantic retrieval of character memories and lore into context</div>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => setAiSettings({ ...aiSettings, ragEnabled: !aiSettings.ragEnabled })}
                                            className={clsx(
                                                "px-3 py-1 rounded-lg text-3xs font-bold uppercase transition-all",
                                                aiSettings.ragEnabled ? "bg-emerald-500/20 border border-emerald-500/30 text-emerald-300" : "bg-gray-800 text-gray-500"
                                            )}
                                        >
                                            {aiSettings.ragEnabled ? 'On' : 'Off'}
                                        </button>
                                    </div>

                                    {aiSettings.ragEnabled && (
                                        <div className="pt-2 space-y-1">
                                            <div className="flex items-center justify-between text-3xs">
                                                <span className="text-gray-400">Semantic Distance Cutoff</span>
                                                <span className="font-mono text-purple-300 font-bold">{aiSettings.ragMaxDistance}</span>
                                            </div>
                                            <input
                                                type="range"
                                                min="0.0"
                                                max="2.0"
                                                step="0.05"
                                                value={aiSettings.ragMaxDistance}
                                                onChange={(e) => setAiSettings({ ...aiSettings, ragMaxDistance: parseFloat(e.target.value) })}
                                                className="w-full accent-purple-500"
                                            />
                                            <div className="flex justify-between text-3xs text-gray-500 font-mono">
                                                <span>0.0 (Strict)</span>
                                                <span>0.6 (Recommended)</span>
                                                <span>2.0 (Top-N)</span>
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {/* Memory Extraction */}
                                <div className="flex items-center justify-between pb-3 border-b border-white/5">
                                    <div>
                                        <div className="text-xs font-semibold text-gray-200">Background Memory Extraction</div>
                                        <div className="text-3xs text-gray-400">Extract durable memory facts from recent conversations</div>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setAiSettings({ ...aiSettings, memoryExtractionEnabled: !aiSettings.memoryExtractionEnabled })}
                                        className={clsx(
                                            "px-3 py-1 rounded-lg text-3xs font-bold uppercase transition-all",
                                            aiSettings.memoryExtractionEnabled ? "bg-emerald-500/20 border border-emerald-500/30 text-emerald-300" : "bg-gray-800 text-gray-500"
                                        )}
                                    >
                                        {aiSettings.memoryExtractionEnabled ? 'On' : 'Off'}
                                    </button>
                                </div>

                                {/* Idle Simulation */}
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <div>
                                            <div className="text-xs font-semibold text-gray-200">Idle Scene Simulation</div>
                                            <div className="text-3xs text-gray-400">Proactive in-character messages while you are away</div>
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => setAiSettings({ ...aiSettings, idleSimEnabled: !aiSettings.idleSimEnabled })}
                                            className={clsx(
                                                "px-3 py-1 rounded-lg text-3xs font-bold uppercase transition-all",
                                                aiSettings.idleSimEnabled ? "bg-emerald-500/20 border border-emerald-500/30 text-emerald-300" : "bg-gray-800 text-gray-500"
                                            )}
                                        >
                                            {aiSettings.idleSimEnabled ? 'On' : 'Off'}
                                        </button>
                                    </div>

                                    {aiSettings.idleSimEnabled && (
                                        <div className="flex items-center gap-2 pt-1 text-xs">
                                            <span className="text-3xs text-gray-400 uppercase">Interval:</span>
                                            <input
                                                type="number"
                                                min="5"
                                                max="1440"
                                                step="5"
                                                value={Math.round((aiSettings.idleSimIntervalSeconds || 600) / 60)}
                                                onChange={(e) => setAiSettings({ ...aiSettings, idleSimIntervalSeconds: (parseInt(e.target.value, 10) || 10) * 60 })}
                                                className="w-20 bg-gray-900 border border-white/10 rounded-lg px-2 py-1 text-xs text-white font-mono"
                                            />
                                            <span className="text-3xs text-gray-500">minutes between checks</span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* System Prompt Blocks Editor */}
                        <div className="glass-panel p-5 rounded-2xl border border-white/10 space-y-5">
                            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/5">
                                <div>
                                    <div className="flex items-center gap-2">
                                        <h4 className="font-bold text-xs uppercase tracking-wider text-white">
                                            System Prompt Blocks &amp; Templates
                                        </h4>
                                        <span className="px-2 py-0.5 rounded-full text-3xs font-semibold bg-purple-500/20 text-purple-300 border border-purple-500/30">
                                            {allPromptMetadata.length} Prompts
                                        </span>
                                        {modifiedPromptCount > 0 && (
                                            <span className="px-2 py-0.5 rounded-full text-3xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">
                                                {modifiedPromptCount} Unsaved
                                            </span>
                                        )}
                                    </div>
                                    <p className="text-3xs text-gray-400 mt-0.5">
                                        Centralized system instructions across Roleplay, Story Sandbox, World Vault, Character Generation, and Prompt Engineering.
                                    </p>
                                </div>
                                <div className="flex items-center gap-2 shrink-0">
                                    {modifiedPromptCount > 0 && (
                                        <button
                                            type="button"
                                            onClick={handleDiscardPrompts}
                                            className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-medium border border-white/10 transition-all"
                                        >
                                            Discard Changes
                                        </button>
                                    )}
                                    <button
                                        type="button"
                                        onClick={() => setNewPromptOpen((v) => !v)}
                                        className="px-3 py-1.5 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-medium border border-white/10 transition-all"
                                        title="Add a system prompt block of your own"
                                    >
                                        {newPromptOpen ? 'Cancel' : '+ Add Prompt'}
                                    </button>
                                    <button
                                        type="button"
                                        onClick={handleSavePrompts}
                                        disabled={savingPrompts}
                                        className="px-4 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold shadow-md shadow-purple-500/20 flex items-center gap-1.5 transition-all disabled:opacity-50"
                                    >
                                        {savingPrompts ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                                        <span>Save Prompts{modifiedPromptCount > 0 ? ` (${modifiedPromptCount})` : ''}</span>
                                    </button>
                                </div>
                            </div>

                            {isErrorPrompts && (
                                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 flex items-center justify-between gap-3 text-amber-200">
                                    <div className="flex items-center gap-2 text-xs">
                                        <AlertCircle size={16} className="text-amber-400 shrink-0" />
                                        <span>
                                            Failed to load system prompt blocks from backend: {errorPrompts?.message || 'Unknown error'}. Showing local defaults.
                                        </span>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => refetchPrompts()}
                                        className="px-3 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 text-xs font-medium border border-amber-500/40 flex items-center gap-1.5 transition-all shrink-0"
                                    >
                                        <RefreshCw size={12} />
                                        <span>Retry</span>
                                    </button>
                                </div>
                            )}

                            {newPromptOpen && (
                                <div className="rounded-xl border border-purple-500/30 bg-purple-500/5 p-3 space-y-2">
                                    <p className="text-3xs text-purple-200/80">
                                        A prompt block of your own. The key is what the rest of the
                                        system looks it up by; the label and category are for you.
                                    </p>
                                    <div className="grid grid-cols-2 gap-2">
                                        <input
                                            type="text"
                                            value={newPromptDraft.key}
                                            onChange={(e) => setNewPromptDraft({ ...newPromptDraft, key: e.target.value })}
                                            placeholder="key (e.g. my_ritual)"
                                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                                        />
                                        <input
                                            type="text"
                                            value={newPromptDraft.label}
                                            onChange={(e) => setNewPromptDraft({ ...newPromptDraft, label: e.target.value })}
                                            placeholder="Label (e.g. The Ritual)"
                                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                                        />
                                    </div>
                                    <input
                                        type="text"
                                        value={newPromptDraft.category}
                                        onChange={(e) => setNewPromptDraft({ ...newPromptDraft, category: e.target.value })}
                                        placeholder="Category"
                                        className="w-full bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                                    />
                                    <textarea
                                        rows={4}
                                        value={newPromptDraft.prompt}
                                        onChange={(e) => setNewPromptDraft({ ...newPromptDraft, prompt: e.target.value })}
                                        placeholder="The prompt text..."
                                        className="w-full bg-gray-900 border border-white/10 rounded-lg p-2.5 font-mono text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50 resize-none"
                                    />
                                    <div className="flex justify-end">
                                        <button
                                            type="button"
                                            onClick={handleAddPrompt}
                                            className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-3xs font-semibold transition-colors"
                                        >
                                            Add Prompt Block
                                        </button>
                                    </div>
                                </div>
                            )}

                            {/* Category Filter Pills & Search */}
                            <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3">
                                <div className="flex flex-wrap items-center gap-1.5">
                                    {SYSTEM_PROMPT_CATEGORIES.map((cat) => {
                                        const count = cat.id === 'all'
                                            ? allPromptMetadata.length
                                            : SYSTEM_PROMPT_METADATA.filter(m => m.category === cat.id).length;
                                        const isActive = promptCategoryFilter === cat.id;
                                        return (
                                            <button
                                                key={cat.id}
                                                type="button"
                                                onClick={() => setPromptCategoryFilter(cat.id)}
                                                className={clsx(
                                                    "px-3 py-1 rounded-xl text-xs font-medium transition-all flex items-center gap-1.5",
                                                    isActive
                                                        ? "bg-purple-600 text-white shadow-md shadow-purple-500/20 font-semibold"
                                                        : "bg-white/5 hover:bg-white/10 text-gray-400 hover:text-gray-200 border border-white/5"
                                                )}
                                            >
                                                <span>{cat.label}</span>
                                                <span className={clsx(
                                                    "px-1.5 py-0.2 rounded-full text-3xs font-mono",
                                                    isActive ? "bg-white/20 text-white" : "bg-black/30 text-gray-400"
                                                )}>
                                                    {count}
                                                </span>
                                            </button>
                                        );
                                    })}
                                </div>

                                <div className="relative w-full md:w-64">
                                    <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                    <input
                                        type="text"
                                        value={promptSearch}
                                        onChange={(e) => setPromptSearch(e.target.value)}
                                        placeholder="Search prompts or variables..."
                                        className="w-full pl-8 pr-3 py-1.5 rounded-xl bg-gray-900/80 border border-white/10 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-purple-500/50"
                                    />
                                    {promptSearch && (
                                        <button
                                            type="button"
                                            onClick={() => setPromptSearch('')}
                                            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-3xs"
                                        >
                                            ✕
                                        </button>
                                    )}
                                </div>
                            </div>

                            {/* Prompt Cards Grid / List */}
                            {isLoadingPrompts ? (
                                <div className="p-8 text-center text-gray-500 text-xs">
                                    <RefreshCw size={18} className="animate-spin mx-auto mb-2 text-purple-400" />
                                    Loading prompt blocks...
                                </div>
                            ) : filteredPrompts.length === 0 ? (
                                <div className="p-8 text-center text-gray-500 text-xs glass-panel rounded-xl border border-white/5">
                                    No system prompts match "{promptSearch}".
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    {filteredPrompts.map((p) => {
                                        const currentVal = promptDraft[p.key] ?? '';
                                        const defaultVal = SYSTEM_PROMPT_DEFAULTS[p.key] ?? '';
                                        const originalSavedVal = blocksData?.blocks?.[p.key] ?? defaultVal;
                                        const isModified = currentVal.trim() !== originalSavedVal.trim();
                                        const categoryObj = SYSTEM_PROMPT_CATEGORIES.find(c => c.id === p.category);

                                        return (
                                            <div
                                                key={p.key}
                                                className={clsx(
                                                    "p-4 rounded-xl border transition-all space-y-2.5",
                                                    isModified
                                                        ? "bg-amber-500/[0.03] border-amber-500/30 shadow-sm shadow-amber-500/5"
                                                        : "bg-white/[0.02] border-white/10 hover:border-white/20"
                                                )}
                                            >
                                                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                                                    <div className="flex items-center gap-2 flex-wrap">
                                                        <span className={clsx(
                                                            "px-2 py-0.5 rounded-md text-3xs font-semibold border",
                                                            categoryObj?.badge || "text-gray-400 bg-white/5 border-white/10"
                                                        )}>
                                                            {categoryObj?.label || p.category}
                                                        </span>
                                                        <span className="font-semibold text-xs text-white">
                                                            {p.label}
                                                        </span>
                                                        <span className="text-3xs text-gray-500 font-mono bg-black/40 px-1.5 py-0.5 rounded border border-white/5">
                                                            {p.key}
                                                        </span>
                                                        {isModified && (
                                                            <span className="px-1.5 py-0.5 rounded-full text-3xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                                                                Modified
                                                            </span>
                                                        )}
                                                    </div>

                                                    <div className="flex items-center gap-1.5 shrink-0">
                                                        {p.custom ? (
                                                            <>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => handleSavePromptLibraryEntry(promptLibrary.find((e) => e.key === p.key) || { key: p.key, label: p.label, category: p.category })}
                                                                    disabled={!isModified}
                                                                    title="Save this prompt block"
                                                                    className="flex items-center gap-1 px-2 py-1 rounded-lg text-3xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors border border-transparent hover:border-white/10 disabled:opacity-40"
                                                                >
                                                                    <Save size={11} />
                                                                    <span>Save</span>
                                                                </button>
                                                                <button
                                                                    type="button"
                                                                    onClick={() => handleRemovePrompt({ key: p.key })}
                                                                    title="Remove this prompt block"
                                                                    className="flex items-center gap-1 px-2 py-1 rounded-lg text-3xs text-gray-500 hover:text-rose-300 hover:bg-rose-500/10 transition-colors border border-transparent hover:border-rose-500/20"
                                                                >
                                                                    <Trash2 size={11} />
                                                                    <span>Remove</span>
                                                                </button>
                                                            </>
                                                        ) : (
                                                            <button
                                                                type="button"
                                                                onClick={() => handleResetPrompt(p.key)}
                                                                title="Reset this prompt to default template"
                                                                className="flex items-center gap-1 px-2 py-1 rounded-lg text-3xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors border border-transparent hover:border-white/10"
                                                            >
                                                                <RotateCcw size={11} />
                                                                <span>Reset to Default</span>
                                                            </button>
                                                        )}
                                                    </div>
                                                </div>

                                                <p className="text-3xs text-gray-400 leading-normal">
                                                    {p.desc}
                                                </p>

                                                {p.variables && p.variables.length > 0 && (
                                                    <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                                                        <span className="text-3xs text-gray-500 uppercase tracking-wider font-semibold">
                                                            Supported Variables:
                                                        </span>
                                                        {p.variables.map((variable) => (
                                                            <button
                                                                key={variable}
                                                                type="button"
                                                                onClick={() => handleCopyVariable(variable)}
                                                                title={`Click to copy "${variable}" tag`}
                                                                className="px-1.5 py-0.5 rounded text-3xs font-mono bg-white/5 hover:bg-purple-500/20 text-purple-300 hover:text-purple-200 border border-white/10 hover:border-purple-500/30 transition-all flex items-center gap-1 cursor-pointer"
                                                            >
                                                                <span>{variable}</span>
                                                                <Copy size={9} className="opacity-60" />
                                                            </button>
                                                        ))}
                                                    </div>
                                                )}

                                                <textarea
                                                    rows={p.rows || 3}
                                                    value={currentVal}
                                                    onChange={(e) => setPromptDraft({ ...promptDraft, [p.key]: e.target.value })}
                                                    className="w-full bg-gray-900/90 border border-white/10 rounded-xl p-2.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-purple-500/50 resize-y leading-relaxed"
                                                />

                                                <div className="flex items-center justify-between text-3xs text-gray-500 font-mono pt-0.5">
                                                    <span>{currentVal.length} characters</span>
                                                    <span>{currentVal.split('\n').length} lines</span>
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* Tab 5: Workflow Simulator */}
                {activeTab === 'simulator' && (
                    <div className="space-y-6">
                        {/* Sub-mode selector */}
                        <div className="flex items-center gap-2 pb-2 border-b border-white/5">
                            <button
                                type="button"
                                onClick={() => setSimMode('pipeline')}
                                className={clsx(
                                    "flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all",
                                    simMode === 'pipeline' ? "bg-amber-600 text-white shadow-md shadow-amber-500/20" : "text-gray-400 hover:text-white hover:bg-white/5"
                                )}
                            >
                                <Play size={13} />
                                <span>Multi-Agent Pipeline</span>
                            </button>
                            <button
                                type="button"
                                onClick={() => setSimMode('director')}
                                className={clsx(
                                    "flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold transition-all",
                                    simMode === 'director' ? "bg-emerald-600 text-white shadow-md shadow-emerald-500/20" : "text-gray-400 hover:text-white hover:bg-white/5"
                                )}
                            >
                                <Sparkles size={13} />
                                <span>System 1 Director Playground</span>
                            </button>
                        </div>

                        {/* Pipeline Simulation Mode */}
                        {simMode === 'pipeline' && (
                            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
                                {/* Input Panel */}
                                <div className="lg:col-span-5 glass-panel p-5 rounded-2xl border border-white/10 space-y-4">
                                    <div className="flex items-center justify-between pb-2 border-b border-white/5">
                                        <div className="flex items-center gap-2">
                                            <Play size={16} className="text-amber-400" />
                                            <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                                                Simulation Scenario
                                            </h3>
                                        </div>
                                        <span className="text-3xs text-gray-500">Test multi-agent pipeline</span>
                                    </div>

                                    <div className="space-y-2">
                                        <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block">
                                            User / Scene Turn Input
                                        </label>
                                        <textarea
                                            rows={4}
                                            value={simScenario}
                                            onChange={(e) => setSimScenario(e.target.value)}
                                            placeholder="Enter the conversational turn or narrative action to test..."
                                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl p-3 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500/50 resize-none"
                                        />
                                    </div>

                                    <div className="grid grid-cols-3 gap-3">
                                        <div>
                                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                                Simulation Stage
                                            </label>
                                            <select
                                                value={simStage}
                                                onChange={(e) => setSimStage(e.target.value)}
                                                className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-amber-500/50"
                                            >
                                                <option value="all">Full Pipeline (All Stages)</option>
                                                <option value="triage">Phase 1: Pre-Gen Triage</option>
                                                <option value="audit">Phase 3: Post-Gen Audit &amp; Gates</option>
                                            </select>
                                        </div>
                                        <div>
                                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                                Gate Threshold ({Math.round(simThreshold * 100)}%)
                                            </label>
                                            <input
                                                type="range"
                                                min="0.10"
                                                max="0.95"
                                                step="0.05"
                                                value={simThreshold}
                                                onChange={(e) => setSimThreshold(parseFloat(e.target.value))}
                                                className="w-full accent-amber-500 mt-2"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                                Illustration Threshold ({Math.round(simImageThreshold * 100)}%)
                                            </label>
                                            <input
                                                type="range"
                                                min="0.10"
                                                max="0.95"
                                                step="0.05"
                                                value={simImageThreshold}
                                                onChange={(e) => setSimImageThreshold(parseFloat(e.target.value))}
                                                className="w-full accent-amber-500 mt-2"
                                            />
                                        </div>
                                    </div>

                                    <div className="space-y-2">
                                        <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block">
                                            Prompt Variant (optional)
                                        </label>
                                        <input
                                            type="text"
                                            value={simVariant}
                                            onChange={(e) => setSimVariant(e.target.value)}
                                            placeholder="variant slug, e.g. cinematic"
                                            className="w-full bg-gray-900/80 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500/50"
                                        />
                                        <p className="text-3xs text-gray-500">
                                            Preview an exact variant, active or not, via its globally unique slug.
                                        </p>
                                    </div>

                                    <button
                                        type="button"
                                        onClick={handleRunSimulation}
                                        disabled={simulateMutation.isPending}
                                        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold shadow-lg shadow-amber-500/20 transition-all disabled:opacity-50"
                                    >
                                        {simulateMutation.isPending ? (
                                            <>
                                                <RefreshCw size={14} className="animate-spin" />
                                                <span>Simulating Pipeline...</span>
                                            </>
                                        ) : (
                                            <>
                                                <Play size={14} />
                                                <span>Run Simulation</span>
                                            </>
                                        )}
                                    </button>
                                </div>

                                {/* Results Panel */}
                                <div className="lg:col-span-7 glass-panel p-5 rounded-2xl border border-white/10 space-y-4">
                                    <div className="flex items-center justify-between pb-2 border-b border-white/5">
                                        <div className="flex items-center gap-2">
                                            <Activity size={16} className="text-emerald-400" />
                                            <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                                                Telemetry &amp; Execution Output
                                            </h3>
                                        </div>
                                        {simResults && (
                                            <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-3xs font-semibold text-emerald-300">
                                                Simulated
                                            </span>
                                        )}
                                    </div>

                                    {!simResults ? (
                                        <div className="p-12 text-center text-gray-500 text-xs">
                                            Run a simulation to observe Laya routing decisions, Fate check resolution, and 16-gate activation telemetry.
                                        </div>
                                    ) : (
                                        <div className="space-y-4 max-h-[600px] overflow-y-auto custom-scrollbar pr-1">
                                            {/* Speaker & Fate Check Summary */}
                                            <div className="grid grid-cols-2 gap-3">
                                                <div className="p-3 rounded-xl bg-gray-900/60 border border-white/5 space-y-1">
                                                    <div className="text-3xs font-semibold text-gray-400 uppercase">Selected Speaker Agent</div>
                                                    <div className="text-sm font-bold text-blue-300">
                                                        {simResults.triage?.next_speaker || simResults.selected_speaker || 'character'}
                                                    </div>
                                                    <div className="text-3xs text-gray-500 font-mono">
                                                        Target: {simResults.target_agent_profile?.name || 'Standard Character'}
                                                    </div>
                                                </div>

                                                <div className="p-3 rounded-xl bg-gray-900/60 border border-white/5 space-y-1">
                                                    <div className="text-3xs font-semibold text-gray-400 uppercase">Fate / Skill Outcome</div>
                                                    <div className="text-sm font-bold text-amber-300">
                                                        {simResults.triage?.fate_outcome || 'Checked (Standard)'}
                                                    </div>
                                                    <div className="text-3xs text-gray-500 font-mono">
                                                        Risky Action Prob: {Math.round((simResults.triage?.is_risky_action_probability || 0) * 100)}%
                                                    </div>
                                                </div>
                                            </div>

                                            {/* 16-Gate Breakdown */}
                                            <div className="p-3 rounded-xl bg-gray-900/60 border border-white/5 space-y-2">
                                                <div className="flex items-center justify-between text-3xs font-semibold text-gray-400 uppercase pb-1 border-b border-white/5">
                                                    <span>16-Gate Statekeeper Audit</span>
                                                    <span className={clsx(
                                                        "px-1.5 py-0.5 rounded font-bold",
                                                        simResults.audit?.should_run_updater ? "bg-purple-500/20 text-purple-300" : "bg-gray-800 text-gray-500"
                                                    )}>
                                                        {simResults.audit?.should_run_updater ? '⚡ Statekeeper Runs' : '⏸️ Idle'}
                                                    </span>
                                                </div>

                                                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
                                                    {Object.entries(simResults.audit?.updater_gates || {}).map(([gateKey, prob]) => {
                                                        const pct = Math.round((prob || 0) * 100);
                                                        const passed = pct >= Math.round(simThreshold * 100);
                                                        const cleanLabel = gateKey.replace('gate_', '').replace(/_/g, ' ');
                                                        return (
                                                            <div
                                                                key={gateKey}
                                                                className={clsx(
                                                                    "p-2 rounded-lg border text-3xs flex flex-col justify-between",
                                                                    passed ? "bg-purple-500/10 border-purple-500/30 text-purple-200" : "bg-gray-800/40 border-white/5 text-gray-500"
                                                                )}
                                                            >
                                                                <div className="font-semibold capitalize truncate">{cleanLabel}</div>
                                                                <div className="flex items-center justify-between mt-1 font-mono">
                                                                    <span>{pct}%</span>
                                                                    {passed && <Check size={10} className="text-purple-400" />}
                                                                </div>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            </div>

                                            {/* Scoped Schema Preview */}
                                            {simResults.audit?.active_gate_keys?.length > 0 && (
                                                <div className="p-3 rounded-xl bg-gray-900/60 border border-white/5 space-y-1.5">
                                                    <div className="text-3xs font-semibold text-purple-300 uppercase">
                                                        Scoped JSON Patch Targets ({simResults.audit.active_gate_keys.length} fields)
                                                    </div>
                                                    <div className="flex flex-wrap gap-1">
                                                        {simResults.audit.active_gate_keys.map(k => (
                                                            <span key={k} className="px-2 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/30 text-purple-200 text-3xs font-mono">
                                                                {k}
                                                            </span>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            {/* Agent Prompt Preview */}
                                            {simResults.agent_profile && (
                                                <div className="p-3 rounded-xl bg-gray-900/60 border border-white/5 space-y-1.5">
                                                    <div className="flex items-center justify-between text-3xs font-semibold text-blue-300 uppercase">
                                                        <span>Rendered Agent Prompt</span>
                                                        <span className="font-mono text-gray-500 normal-case">
                                                            {simResults.agent_profile.slug}
                                                            {simResults.agent_profile.variant_slug
                                                                ? ` · variant:${simResults.agent_profile.variant_slug}`
                                                                : ' · base template'}
                                                        </span>
                                                    </div>
                                                    <pre className="whitespace-pre-wrap break-words font-mono text-3xs text-gray-300 leading-relaxed">
                                                        {simResults.agent_profile.rendered_prompt_preview}
                                                    </pre>
                                                </div>
                                            )}
                                            {simResults.agent_profile_error && (
                                                <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-3xs text-rose-300">
                                                    {simResults.agent_profile_error}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* System 1 Director Playground Mode */}
                        {simMode === 'director' && (
                            <div className="glass-panel p-5 rounded-2xl border border-emerald-500/20 bg-emerald-950/10 space-y-4">
                                <div className="flex items-center justify-between pb-2 border-b border-white/5">
                                    <div className="flex items-center gap-2">
                                        <Sparkles size={16} className="text-emerald-400" />
                                        <h3 className="font-bold text-xs uppercase tracking-wider text-white">
                                            System 1 Director &amp; Gate Tester (13 Parallel Typed Decisions)
                                        </h3>
                                    </div>
                                    <span className="text-3xs text-emerald-400 font-mono">CPU / RAM NLI Engine</span>
                                </div>

                                <p className="text-xs text-gray-400">
                                    Test how the System 1 Decision Maker (Laya CPU/RAM or fallback) evaluates dialogue in parallel: next speaker, scene tension, pacing directive, character visual expression, and Statekeeper world-update gates.
                                </p>

                                <textarea
                                    rows={3}
                                    value={directorDialogue}
                                    onChange={(e) => setDirectorDialogue(e.target.value)}
                                    aria-label="Sample dialogue for Director evaluation"
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-xs text-gray-200 font-mono focus:outline-none focus:border-emerald-500/50"
                                />

                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div className="flex flex-wrap items-center gap-4 text-xs text-gray-300">
                                        <label className="flex items-center gap-1.5">
                                            <span className="text-gray-400 text-3xs uppercase font-semibold">Last Speaker:</span>
                                            <select
                                                value={directorLastSpeaker}
                                                onChange={(e) => setDirectorLastSpeaker(e.target.value)}
                                                className="bg-gray-900 border border-white/10 rounded-lg px-2 py-1 text-xs text-white"
                                            >
                                                <option value="user">User</option>
                                                <option value="character">Character</option>
                                                <option value="narrator">Narrator</option>
                                            </select>
                                        </label>
                                        <label className="flex items-center gap-1.5 cursor-pointer text-xs">
                                            <input
                                                type="checkbox"
                                                checked={directorHasSecondary}
                                                onChange={(e) => setDirectorHasSecondary(e.target.checked)}
                                                className="accent-emerald-500"
                                            />
                                            <span className="text-gray-300">Multi-character scene</span>
                                        </label>
                                    </div>

                                    <button
                                        type="button"
                                        onClick={handleRunDirectorEval}
                                        disabled={evalDirectorMutation.isPending}
                                        className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold flex items-center gap-2 shadow-md shadow-emerald-500/20 transition-all disabled:opacity-50"
                                    >
                                        {evalDirectorMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                                        <span>Evaluate 13 Typed Questions</span>
                                    </button>
                                </div>

                                {evalDirectorMutation.data && (
                                    <div className="mt-4 pt-4 border-t border-white/10 space-y-4 text-xs">
                                        <div className="flex flex-wrap items-center justify-between gap-2 bg-black/30 px-3 py-2 rounded-xl border border-white/5">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <span className="px-2 py-0.5 rounded bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 font-bold uppercase text-3xs font-mono">
                                                    Tier: {evalDirectorMutation.data.provider_tier}
                                                </span>
                                                <span className="text-gray-400 font-mono text-3xs">
                                                    Model: {evalDirectorMutation.data.model_id}
                                                </span>
                                                <span className="text-emerald-400 font-mono text-3xs">
                                                    ⚡ {evalDirectorMutation.data.latency_ms} ms
                                                </span>
                                            </div>
                                            <div className="text-3xs font-semibold text-gray-300">
                                                Next Turn: <span className="text-emerald-300 uppercase font-bold">{evalDirectorMutation.data.next_speaker}</span>
                                                {' • '}
                                                Tension: <span className="text-amber-300 font-bold">{evalDirectorMutation.data.scene_tension}/5 ({evalDirectorMutation.data.scene_tension_label})</span>
                                            </div>
                                        </div>

                                        <div className="grid gap-3 md:grid-cols-3">
                                            <div className="bg-black/30 p-3 rounded-xl border border-white/5 space-y-1.5">
                                                <div className="text-3xs uppercase tracking-wider text-gray-400 font-bold">Turn &amp; Pacing</div>
                                                <div className="text-gray-300"><b>Speaker:</b> <span className="text-emerald-300">{evalDirectorMutation.data.next_speaker}</span></div>
                                                <div className="text-gray-300"><b>Directive:</b> <span className="text-blue-300">{evalDirectorMutation.data.pacing_directive}</span></div>
                                                <div className="text-gray-300"><b>Speed:</b> {evalDirectorMutation.data.pacing_speed_label} ({evalDirectorMutation.data.pacing_speed}/4)</div>
                                                <div className="text-gray-300"><b>Tone:</b> <span className="text-purple-300">{evalDirectorMutation.data.emotional_tone}</span></div>
                                                <div className="text-gray-300"><b>Continue Chain:</b> {Math.round((evalDirectorMutation.data.continue_chain_prob || 0) * 100)}%</div>
                                            </div>

                                            <div className="bg-black/30 p-3 rounded-xl border border-white/5 space-y-1.5">
                                                <div className="text-3xs uppercase tracking-wider text-gray-400 font-bold">Visuals &amp; Fate Check</div>
                                                <div className="text-gray-300"><b>Expression:</b> <span className="text-amber-300">{evalDirectorMutation.data.character_expression}</span></div>
                                                <div className="text-gray-300"><b>Image Focus:</b> {evalDirectorMutation.data.image_focus}</div>
                                                <div className="text-gray-300"><b>Trigger Image:</b> {Math.round((evalDirectorMutation.data.trigger_image_prob || 0) * 100)}%</div>
                                                <div className="text-gray-300">
                                                    <b>Action Risk:</b>{' '}
                                                    <span className="text-amber-300">
                                                        {Math.round((evalDirectorMutation.data.is_risky_action_probability || 0) * 100)}% ({evalDirectorMutation.data.action_difficulty_label || 'normal'})
                                                    </span>
                                                </div>
                                                {evalDirectorMutation.data.director_instruction && (
                                                    <div className="mt-1 pt-1 border-t border-white/5 text-3xs text-gray-400 italic">
                                                        &ldquo;{evalDirectorMutation.data.director_instruction}&rdquo;
                                                    </div>
                                                )}
                                            </div>

                                            <div className="bg-black/30 p-3 rounded-xl border border-white/5 space-y-1.5">
                                                <div className="flex items-center justify-between">
                                                    <span className="text-3xs uppercase tracking-wider text-gray-400 font-bold">Statekeeper Gates</span>
                                                    <span className={clsx("px-1.5 py-0.5 rounded text-3xs font-bold", evalDirectorMutation.data.should_run_updater ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30' : 'bg-gray-800 text-gray-500')}>
                                                        {evalDirectorMutation.data.should_run_updater ? 'UPDATER FIRES' : 'IDLE'}
                                                    </span>
                                                </div>
                                                {[
                                                    ['Location / Time', evalDirectorMutation.data.updater_gates?.gate_world_state],
                                                    ['Char / Outfit / Rel', evalDirectorMutation.data.updater_gates?.gate_character_state],
                                                    ['Inventory / Items', evalDirectorMutation.data.updater_gates?.gate_inventory_or_items],
                                                    ['Durable Memory', evalDirectorMutation.data.updater_gates?.gate_durable_memory],
                                                    ['Lore Discovery', evalDirectorMutation.data.updater_gates?.gate_lore_discovery],
                                                ].map(([label, prob]) => {
                                                    const pct = Math.round((prob || 0) * 100);
                                                    const active = (prob || 0) >= 0.55;
                                                    return (
                                                        <div key={label} className="space-y-0.5">
                                                            <div className="flex justify-between text-3xs">
                                                                <span className={active ? 'text-purple-300 font-semibold' : 'text-gray-400'}>{label}</span>
                                                                <span className="font-mono text-gray-400">{pct}%</span>
                                                            </div>
                                                            <div className="w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                                                                <div
                                                                    className={clsx("h-full rounded-full", active ? 'bg-purple-400' : 'bg-gray-600')}
                                                                    style={{ width: `${Math.min(100, Math.max(4, pct))}%` }}
                                                                />
                                                            </div>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Agent Modal (Create / Edit) */}
            {showAgentModal && (
                <AgentModal
                    agent={editingAgent}
                    availableModels={availableModels}
                    onClose={() => {
                        setShowAgentModal(false);
                        setEditingAgent(null);
                    }}
                    onSave={async (formData) => {
                        if (editingAgent) {
                            await updateAgentMutation.mutateAsync({ id: editingAgent.id, ...formData });
                            toast.success(`Agent "${formData.name}" updated.`);
                        } else {
                            await createAgentMutation.mutateAsync(formData);
                            toast.success(`Agent "${formData.name}" created.`);
                        }
                        setShowAgentModal(false);
                        setEditingAgent(null);
                    }}
                />
            )}
        </div>
    );
}

function AgentAvatarField({ agent }) {
    const uploadAvatar = useUploadAgentAvatar();
    const inputRef = useRef(null);
    const [preview, setPreview] = useState(null);

    // The saved avatar is served by the backend; the local preview is only
    // there so the image appears the instant it is picked, before the
    // upload round-trips.
    const src = preview || (agent.avatar_path ? getAgentAvatarUrl(agent.id) : null);

    const handleFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;
        setPreview(URL.createObjectURL(file));
        try {
            await uploadAvatar.mutateAsync({ agentId: agent.id, file });
            toast.success('Avatar uploaded.');
            setPreview(null);
        } catch (err) {
            setPreview(null);
            toast.error(err?.message || 'Avatar upload failed.');
        }
    };

    return (
        <div className="flex items-center gap-4 rounded-xl border border-white/5 bg-black/20 p-3">
            <div className="h-16 w-16 shrink-0 overflow-hidden rounded-xl border border-white/10 bg-gray-900 flex items-center justify-center">
                {src ? (
                    <img src={src} alt="" className="h-full w-full object-cover" />
                ) : (
                    <Bot size={22} className="text-gray-600" />
                )}
            </div>
            <div className="min-w-0 flex-1">
                <p className="text-3xs font-semibold text-gray-400 uppercase tracking-wider">Avatar</p>
                <p className="mt-1 text-3xs text-gray-500">
                    Shown wherever this agent is picked. PNG or WebP, up to 5 MB.
                </p>
                <input
                    ref={inputRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    onChange={handleFile}
                    className="hidden"
                />
                <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    disabled={uploadAvatar.isPending}
                    className="mt-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 text-3xs font-semibold transition-colors disabled:opacity-50"
                >
                    {uploadAvatar.isPending ? 'Uploading…' : (src ? 'Replace avatar' : 'Upload avatar')}
                </button>
            </div>
        </div>
    );
}

function AgentModal({ agent, availableModels = [], onClose, onSave }) {
    const isBuiltin = Boolean(agent?.is_builtin);
    const [name, setName] = useState(agent?.name || '');
    const [slug, setSlug] = useState(agent?.slug || '');
    const [agentType, setAgentType] = useState(agent?.agent_type || 'character');
    const [description, setDescription] = useState(agent?.description || '');
    const [systemPromptTemplate, setSystemPromptTemplate] = useState(agent?.system_prompt_template || '');
    const [modelTarget, setModelTarget] = useState(agent?.model_target || 'rp');
    const [modelOverride, setModelOverride] = useState(agent?.model_override || '');
    const [temperature, setTemperature] = useState(agent?.temperature ?? '');
    const [topP, setTopP] = useState(agent?.top_p ?? '');
    const [maxTokens, setMaxTokens] = useState(agent?.max_tokens ?? '');
    const [enabled, setEnabled] = useState(agent?.enabled !== false);
    const [saving, setSaving] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!name.trim() || !slug.trim()) {
            toast.error('Name and slug are required.');
            return;
        }
        setSaving(true);
        try {
            await onSave({
                name,
                slug,
                agent_type: agentType,
                description,
                system_prompt_template: systemPromptTemplate,
                model_target: modelTarget,
                model_override: modelOverride || null,
                temperature: temperature === '' ? null : parseFloat(temperature),
                top_p: topP === '' ? null : parseFloat(topP),
                max_tokens: maxTokens === '' ? null : parseInt(maxTokens, 10),
                enabled,
            });
        } catch {
            toast.error('Failed to save agent');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-150">
            <div className="glass-panel w-full max-w-2xl rounded-2xl border border-white/10 bg-[#0F131C] p-6 space-y-4 max-h-[90vh] overflow-y-auto custom-scrollbar shadow-2xl">
                <div className="flex items-center justify-between pb-3 border-b border-white/5">
                    <div>
                        <h2 className="text-base font-bold text-white">
                            {agent ? (isBuiltin ? `View Agent: ${agent.name}` : `Edit Agent: ${agent.name}`) : 'Create Custom Agent'}
                        </h2>
                        <p className="text-3xs text-gray-400">
                            Configure prompt instructions, model routing, and Laya triage descriptions.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-white/5"
                    >
                        ✕
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="space-y-4 text-xs">
                    {agent?.id && (
                        <AgentAvatarField agent={agent} />
                    )}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Agent Name
                            </label>
                            <input
                                type="text"
                                value={name}
                                onChange={(e) => {
                                    setName(e.target.value);
                                    if (!agent) {
                                        setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'));
                                    }
                                }}
                                disabled={isBuiltin}
                                placeholder="e.g. Dungeon Master"
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            />
                        </div>

                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Slug Identifier
                            </label>
                            <input
                                type="text"
                                value={slug}
                                onChange={(e) => setSlug(e.target.value)}
                                disabled={isBuiltin}
                                placeholder="e.g. dungeon_master"
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 font-mono text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            />
                        </div>
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Agent Type
                            </label>
                            <select
                                value={agentType}
                                onChange={(e) => setAgentType(e.target.value)}
                                disabled={isBuiltin}
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-gray-200 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            >
                                <option value="character">Character (Dialogue &amp; persona)</option>
                                <option value="narrator">Narrator (Scene setting &amp; pacing)</option>
                                <option value="specialist">Specialist (Domain expertise)</option>
                            </select>
                        </div>

                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Model Target
                            </label>
                            <select
                                value={modelTarget}
                                onChange={(e) => setModelTarget(e.target.value)}
                                disabled={isBuiltin}
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-gray-200 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            >
                                <option value="rp">Roleplay Model (RP Engine)</option>
                                <option value="util">Utility Model (Util Engine)</option>
                            </select>
                        </div>

                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Model Override (Optional)
                            </label>
                            <input
                                type="text"
                                list="available-models-list"
                                value={modelOverride}
                                onChange={(e) => setModelOverride(e.target.value)}
                                disabled={isBuiltin}
                                placeholder="Default cluster"
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            />
                            <datalist id="available-models-list">
                                {availableModels.map((m) => (
                                    <option key={m} value={m} />
                                ))}
                            </datalist>
                        </div>
                    </div>

                    <div>
                        <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                            Laya Routing Description (When should Laya choose this speaker?)
                        </label>
                        <textarea
                            rows={2}
                            value={description}
                            onChange={(e) => setDescription(e.target.value)}
                            disabled={isBuiltin}
                            placeholder="e.g. Choose this agent when the scene requires objective environmental narration, combat consequences, or world descriptions."
                            className="w-full bg-gray-900 border border-white/10 rounded-xl p-2.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50 resize-none"
                        />
                    </div>

                    <div>
                        <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                            System Prompt Template
                        </label>
                        <textarea
                            rows={5}
                            value={systemPromptTemplate}
                            onChange={(e) => setSystemPromptTemplate(e.target.value)}
                            disabled={isBuiltin}
                            placeholder="You are the Dungeon Master. Maintain strict physical realism and enforce consequences..."
                            className="w-full bg-gray-900 border border-white/10 rounded-xl p-2.5 font-mono text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50 resize-none"
                        />
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Temperature
                            </label>
                            <input
                                type="number"
                                step="0.05"
                                min="0"
                                max="2"
                                value={temperature}
                                onChange={(e) => setTemperature(e.target.value)}
                                disabled={isBuiltin}
                                placeholder="Default"
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            />
                        </div>

                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Top P
                            </label>
                            <input
                                type="number"
                                step="0.05"
                                min="0"
                                max="1"
                                value={topP}
                                onChange={(e) => setTopP(e.target.value)}
                                disabled={isBuiltin}
                                placeholder="Default"
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            />
                        </div>

                        <div>
                            <label className="text-3xs font-semibold text-gray-400 uppercase tracking-wider block mb-1">
                                Max Tokens
                            </label>
                            <input
                                type="number"
                                step="32"
                                min="64"
                                max="4096"
                                value={maxTokens}
                                onChange={(e) => setMaxTokens(e.target.value)}
                                disabled={isBuiltin}
                                placeholder="Default"
                                className="w-full bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 disabled:opacity-50"
                            />
                        </div>
                    </div>

                    {agent?.id && <AgentVariantsSection agent={agent} variants={agent.variants} />}

                    <div className="flex items-center justify-between pt-2">
                        <label className="flex items-center gap-2 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={enabled}
                                onChange={(e) => setEnabled(e.target.checked)}
                                disabled={isBuiltin}
                                className="accent-blue-500 disabled:opacity-50"
                            />
                            <span className="text-xs text-gray-300 font-medium">Active &amp; Available for Laya Routing</span>
                        </label>

                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={onClose}
                                className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-semibold transition-colors"
                            >
                                {isBuiltin ? 'Close' : 'Cancel'}
                            </button>

                            {!isBuiltin && (
                                <button
                                    type="submit"
                                    disabled={saving}
                                    className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 transition-all disabled:opacity-50"
                                >
                                    {saving ? 'Saving...' : 'Save Agent'}
                                </button>
                            )}
                        </div>
                    </div>
                </form>
            </div>
        </div>
    );
}

/**
 * The cross-agent prompt library.
 *
 * A variant used to be reachable only through the agent that owns it, so
 * "what prompts do I have" meant opening each agent in turn. This lists every
 * variant of every agent in one place, and shows the two scopes that decide
 * when each one applies: the model it is written for, and the Statekeeper
 * gate it fires on.
 */
function PromptLibraryTab({ agents = [] }) {
    const { data: agentsWithVariants = [] } = useAgentsWithVariants();
    const [agentFilter, setAgentFilter] = useState('all');
    const [scopeFilter, setScopeFilter] = useState('all');
    const [search, setSearch] = useState('');
    const [editing, setEditing] = useState(null);
    const [draft, setDraft] = useState('');

    const updateVariant = useUpdateAgentVariant();

    const rows = useMemo(() => {
        const out = [];
        for (const agent of agentsWithVariants) {
            for (const variant of agent.variants || []) {
                out.push({
                    agentSlug: agent.slug,
                    agentName: agent.name,
                    // The variant carries its own agent id; the agent's id is
                    // the fallback for a payload that does not.
                    agentId: variant.agent_id || agent.id,
                    variant,
                });
            }
        }
        return out;
    }, [agentsWithVariants]);

    const filtered = useMemo(() => {
        return rows.filter(({ agentSlug, variant }) => {
            if (agentFilter !== 'all' && agentSlug !== agentFilter) return false;
            if (scopeFilter === 'model' && !variant.model_scope) return false;
            if (scopeFilter === 'gate' && !variant.gate_scope) return false;
            if (scopeFilter === 'unscoped' && (variant.model_scope || variant.gate_scope)) return false;
            if (scopeFilter === 'unselectable' && (variant.selection_hint || variant.description)) return false;
            if (!search.trim()) return true;
            const q = search.toLowerCase();
            return (
                (variant.name || '').toLowerCase().includes(q) ||
                (variant.slug || '').toLowerCase().includes(q) ||
                (variant.system_prompt_template || '').toLowerCase().includes(q) ||
                agentSlug.toLowerCase().includes(q) ||
                (Array.isArray(variant.tags) ? variant.tags.join(' ').toLowerCase().includes(q) : false)
            );
        });
    }, [rows, agentFilter, scopeFilter, search]);

    const handleSave = async (row) => {
        try {
            await updateVariant.mutateAsync({
                agentId: row.agentId,
                variantId: row.variant.id,
                system_prompt_template: draft.trim(),
            });
            toast.success(`Saved "${row.variant.name}".`);
            setEditing(null);
        } catch (err) {
            toast.error(err?.message || 'Could not save the variant.');
        }
    };

    return (
        <div className="space-y-4">
            <div className="glass-panel p-4 rounded-2xl border border-white/10">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div>
                        <h4 className="font-bold text-xs uppercase tracking-wider text-white flex items-center gap-2">
                            <Library size={14} className="text-fuchsia-300" />
                            Prompt Library
                        </h4>
                        <p className="text-3xs text-gray-400 mt-0.5">
                            Every prompt variant of every agent. A variant with a model scope is only
                            offered to Laya when that agent answers with that model; one with a gate
                            scope is used by the Statekeeper when that gate fires.
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                        <input
                            type="text"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="Search prompts..."
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-fuchsia-500/50"
                        />
                        <select
                            value={agentFilter}
                            onChange={(e) => setAgentFilter(e.target.value)}
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-300 focus:outline-none focus:border-fuchsia-500/50"
                        >
                            <option value="all">All agents</option>
                            {(agents.length ? agents : agentsWithVariants).map((a) => (
                                <option key={a.slug} value={a.slug}>{a.name}</option>
                            ))}
                        </select>
                        <select
                            value={scopeFilter}
                            onChange={(e) => setScopeFilter(e.target.value)}
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-300 focus:outline-none focus:border-fuchsia-500/50"
                        >
                            <option value="all">Any scope</option>
                            <option value="model">Model-scoped</option>
                            <option value="gate">Gate-scoped</option>
                            <option value="unscoped">Unscoped</option>
                            <option value="unselectable">Not selectable by Laya</option>
                        </select>
                    </div>
                </div>
            </div>

            <div className="glass-panel p-4 rounded-2xl border border-white/10 space-y-2">
                {filtered.length === 0 ? (
                    <p className="text-xs text-gray-500 text-center py-6">
                        No prompt variants match.
                    </p>
                ) : (
                    filtered.map(({ agentSlug, variant }) => {
                        const isEditing = editing === variant.id;
                        return (
                            <div key={variant.id} className="rounded-xl border border-white/10 bg-white/[0.02] p-3 space-y-1.5">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 text-3xs font-mono">
                                        {agentSlug}
                                    </span>
                                    <span className="font-semibold text-xs text-white">{variant.name}</span>
                                    <span className="text-3xs text-gray-500 font-mono">{variant.slug}</span>
                                    {variant.model_scope && (
                                        <span className="px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 font-mono text-3xs">
                                            model:{variant.model_scope}
                                        </span>
                                    )}
                                    {variant.gate_scope && (
                                        <span className="px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 font-mono text-3xs">
                                            gate:{variant.gate_scope}
                                        </span>
                                    )}
                                    {variant.is_active && (
                                        <span className="px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-bold uppercase text-3xs">Active</span>
                                    )}
                                    {!variant.selection_hint && !variant.description && (
                                        <span className="px-1.5 py-0.5 rounded-full bg-rose-500/15 text-rose-300 font-bold uppercase text-3xs">
                                            Not selectable by Laya
                                        </span>
                                    )}
                                    <div className="ml-auto flex items-center gap-1.5">
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setEditing(isEditing ? null : variant.id);
                                                setDraft(variant.system_prompt_template || '');
                                            }}
                                            className="px-2 py-1 rounded-lg text-3xs text-gray-400 hover:text-white hover:bg-white/10 transition-colors"
                                        >
                                            {isEditing ? 'Cancel' : 'Edit'}
                                        </button>
                                        {isEditing && (
                                            <button
                                                type="button"
                                                onClick={() => handleSave({ variant })}
                                                className="px-2 py-1 rounded-lg bg-fuchsia-600 hover:bg-fuchsia-500 text-white text-3xs font-semibold transition-colors"
                                            >
                                                Save
                                            </button>
                                        )}
                                    </div>
                                </div>
                                {isEditing ? (
                                    <textarea
                                        rows={5}
                                        value={draft}
                                        onChange={(e) => setDraft(e.target.value)}
                                        className="w-full bg-gray-900 border border-white/10 rounded-lg p-2.5 font-mono text-3xs text-gray-200 focus:outline-none focus:border-fuchsia-500/50 resize-none"
                                    />
                                ) : (
                                    <p className="text-3xs text-gray-400 font-mono leading-relaxed whitespace-pre-wrap break-words">
                                        {variant.system_prompt_template}
                                    </p>
                                )}
                                {variant.selection_hint && (
                                    <p className="text-3xs text-purple-300/70">
                                        Hint: {variant.selection_hint}
                                    </p>
                                )}
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}

function AgentVariantsSection({ agent, variants: providedVariants }) {
    const { confirm } = useConfirmation();
    // The parent already loaded every agent together with its variants in one
    // request, so the per-agent query is only needed when that list is not
    // available (a direct mount of this section).
    const { data: fetchedVariants = [], isLoading } = useAgentVariants(agent.id, {
        enabled: !providedVariants,
    });
    const variants = providedVariants ?? fetchedVariants;
    const createVariant = useCreateAgentVariant();
    const updateVariant = useUpdateAgentVariant();
    const deleteVariant = useDeleteAgentVariant();
    const activateVariant = useActivateAgentVariant();

    const [showForm, setShowForm] = useState(false);
    const [editing, setEditing] = useState(null);
    const [name, setName] = useState('');
    const [slug, setSlug] = useState('');
    const [tags, setTags] = useState('');
    const [selectionHint, setSelectionHint] = useState('');
    const [modelScope, setModelScope] = useState('');
    const [gateScope, setGateScope] = useState('');
    const [prompt, setPrompt] = useState('');
    const [temperature, setTemperature] = useState('');
    const [topP, setTopP] = useState('');
    const [maxTokens, setMaxTokens] = useState('');
    const [activate, setActivate] = useState(false);
    const [saving, setSaving] = useState(false);

    const resetForm = () => {
        setEditing(null);
        setName('');
        setSlug('');
        setTags('');
        setSelectionHint('');
        setModelScope('');
        setGateScope('');
        setPrompt('');
        setTemperature('');
        setTopP('');
        setMaxTokens('');
        setActivate(false);
        setShowForm(false);
    };

    const startCreate = () => {
        resetForm();
        setShowForm(true);
    };

    const startEdit = (variant) => {
        setEditing(variant);
        setName(variant.name);
        setSlug(variant.slug);
        setTags(Array.isArray(variant.tags) ? variant.tags.join(', ') : '');
        setSelectionHint(variant.selection_hint || '');
        setModelScope(variant.model_scope || '');
        setGateScope(variant.gate_scope || '');
        setPrompt(variant.system_prompt_template);
        setTemperature(variant.temperature ?? '');
        setTopP(variant.top_p ?? '');
        setMaxTokens(variant.max_tokens ?? '');
        setActivate(Boolean(variant.is_active));
        setShowForm(true);
    };

    const handleSave = async () => {
        if (!name.trim() || !slug.trim()) {
            toast.error('Variant name and slug are required.');
            return;
        }
        if (prompt.trim().length < 10) {
            toast.error('Variant prompt must be at least 10 characters.');
            return;
        }
        const payload = {
            name: name.trim(),
            system_prompt_template: prompt.trim(),
            tags: tags.split(',').map(t => t.trim()).filter(Boolean),
            selection_hint: selectionHint.trim(),
            model_scope: modelScope.trim() || null,
            gate_scope: gateScope.trim() || null,
            temperature: temperature === '' ? null : parseFloat(temperature),
            top_p: topP === '' ? null : parseFloat(topP),
            max_tokens: maxTokens === '' ? null : parseInt(maxTokens, 10),
        };
        setSaving(true);
        try {
            if (editing) {
                await updateVariant.mutateAsync({
                    agentId: agent.id,
                    variantId: editing.id,
                    ...payload,
                    is_active: activate,
                });
                toast.success(`Variant "${payload.name}" updated.`);
            } else {
                await createVariant.mutateAsync({
                    agentId: agent.id,
                    ...payload,
                    slug: slug.trim(),
                    description: '',
                    activate,
                });
                toast.success(`Variant "${payload.name}" created.`);
            }
            resetForm();
        } finally {
            setSaving(false);
        }
    };

    const handleActivate = async (variant) => {
        try {
            await activateVariant.mutateAsync({ agentId: agent.id, variantId: variant.id });
            toast.success(`Variant "${variant.name}" is now active.`);
        } catch {
            toast.error('Failed to activate variant');
        }
    };

    const handleDelete = async (variant) => {
        const ok = await confirm({
            title: `Delete variant "${variant.name}"?`,
            message: 'The agent falls back to its base template when no variant is active.',
            confirmText: 'Delete Variant',
            isDangerous: true,
        });
        if (!ok) return;
        try {
            await deleteVariant.mutateAsync({ agentId: agent.id, variantId: variant.id });
            toast.success(`Variant "${variant.name}" deleted.`);
        } catch {
            toast.error('Failed to delete variant');
        }
    };

    return (
        <div className="rounded-xl border border-purple-500/20 bg-purple-950/10 p-3 space-y-3">
            <div className="flex items-center justify-between">
                <div>
                    <div className="flex items-center gap-1.5 text-3xs font-semibold text-purple-200 uppercase tracking-wider">
                        <Layers size={11} />
                        <span>Prompt Variants ({variants.length})</span>
                    </div>
                    <p className="text-3xs text-gray-400 mt-0.5">
                        Alternate prompts and sub-variants for this agent. Laya System 1 uses tags and selection hints to dynamically route situational beats.
                    </p>
                </div>
                <button
                    type="button"
                    onClick={startCreate}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-purple-600/20 hover:bg-purple-600/30 border border-purple-500/30 text-purple-200 text-3xs font-semibold transition-colors shrink-0"
                >
                    <Plus size={11} />
                    <span>New Variant</span>
                </button>
            </div>

            {isLoading ? (
                <div className="text-3xs text-gray-500 flex items-center gap-1.5">
                    <RefreshCw size={11} className="animate-spin" /> Loading variants...
                </div>
            ) : variants.length === 0 ? (
                <div className="text-3xs text-gray-500 italic">No variants yet. The base template is in use.</div>
            ) : (
                <div className="space-y-1.5">
                    {variants.map((variant) => (
                        <div
                            key={variant.id}
                            className={clsx(
                                "flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-lg border text-3xs",
                                variant.is_active
                                    ? "bg-emerald-500/10 border-emerald-500/30"
                                    : "bg-gray-900/50 border-white/5"
                            )}
                        >
                            <div className="min-w-0">
                                <div className="flex items-center gap-1.5 flex-wrap">
                                    <span className="font-semibold text-gray-200 truncate">{variant.name}</span>
                                    <span className="font-mono text-gray-500 truncate">variant:{variant.slug}</span>
                                    {variant.is_active && (
                                        <span className="px-1.5 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 font-bold uppercase text-3xs">Active</span>
                                    )}
                                    {variant.model_scope && (
                                        <span
                                            className="px-1.5 py-0.5 rounded-full bg-cyan-500/15 text-cyan-300 font-mono text-3xs"
                                            title={`Only offered when the agent answers with this model or role. Current scope: ${variant.model_scope}`}
                                        >
                                            model:{variant.model_scope}
                                        </span>
                                    )}
                                    {variant.gate_scope && (
                                        <span
                                            className="px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 font-mono text-3xs"
                                            title={`Only used when this Statekeeper gate fires. Current gate: ${variant.gate_scope}`}
                                        >
                                            gate:{variant.gate_scope}
                                        </span>
                                    )}
                                    {!variant.selection_hint && !variant.description && (
                                        <span
                                            className="px-1.5 py-0.5 rounded-full bg-rose-500/15 text-rose-300 font-bold uppercase text-3xs"
                                            title="Laya is never offered a variant with no selection hint and no description, so this one can only be used by naming it."
                                        >
                                            Not selectable by Laya
                                        </span>
                                    )}
                                    {Array.isArray(variant.tags) && variant.tags.map((t) => (
                                        <span key={t} className="px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300 text-3xs font-mono">
                                            #{t}
                                        </span>
                                    ))}
                                </div>
                                {variant.selection_hint && (
                                    <div className="text-purple-300/80 truncate text-3xs">Hint: {variant.selection_hint}</div>
                                )}
                                <div className="text-gray-500 truncate">{variant.system_prompt_template}</div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                                {!variant.is_active && (
                                    <button
                                        type="button"
                                        onClick={() => handleActivate(variant)}
                                        className="p-1 rounded text-gray-400 hover:text-emerald-300 hover:bg-emerald-500/10"
                                        title="Activate variant"
                                    >
                                        <Check size={12} />
                                    </button>
                                )}
                                <button
                                    type="button"
                                    onClick={() => startEdit(variant)}
                                    className="p-1 rounded text-gray-400 hover:text-blue-300 hover:bg-blue-500/10"
                                    title="Edit variant"
                                >
                                    <Edit2 size={12} />
                                </button>
                                <button
                                    type="button"
                                    onClick={() => handleDelete(variant)}
                                    className="p-1 rounded text-gray-500 hover:text-rose-400 hover:bg-rose-500/10"
                                    title="Delete variant"
                                >
                                    <Trash2 size={12} />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {showForm && (
                <div className="rounded-lg border border-white/10 bg-gray-950/60 p-3 space-y-2">
                    <div className="grid grid-cols-2 gap-2">
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => {
                                setName(e.target.value);
                                if (!editing) {
                                    setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_'));
                                }
                            }}
                            placeholder="Variant name"
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                        />
                        <input
                            type="text"
                            value={slug}
                            onChange={(e) => setSlug(e.target.value)}
                            disabled={Boolean(editing)}
                            placeholder="variant_slug"
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 font-mono text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50 disabled:opacity-50"
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                        <input
                            type="text"
                            value={tags}
                            onChange={(e) => setTags(e.target.value)}
                            placeholder="Tags: combat, quiet, intimate (comma-separated)"
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                        />
                        <input
                            type="text"
                            value={selectionHint}
                            onChange={(e) => setSelectionHint(e.target.value)}
                            placeholder="Laya selection hint (e.g. Physical combat beats)"
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                        <label className="block">
                            <span className="text-3xs text-gray-500 block mb-1">
                                Model scope <span className="text-gray-600">(blank = any model)</span>
                            </span>
                            <input
                                type="text"
                                value={modelScope}
                                onChange={(e) => setModelScope(e.target.value)}
                                placeholder="rp, util — or a model id"
                                className="w-full bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                            />
                        </label>
                        <label className="block">
                            <span className="text-3xs text-gray-500 block mb-1">
                                Gate scope <span className="text-gray-600">(blank = any gate)</span>
                            </span>
                            <input
                                type="text"
                                value={gateScope}
                                onChange={(e) => setGateScope(e.target.value)}
                                placeholder="gate_character_mood"
                                className="w-full bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                            />
                        </label>
                    </div>
                    <p className="text-3xs text-gray-600 leading-relaxed">
                        A model-scoped variant is only offered to Laya when the agent answers with that
                        model or role, and is applied automatically when it matches. A gate-scoped variant
                        is used by the Statekeeper when that gate fires. Both are how "a different prompt
                        for a different LLM" and "a prompt for the mood that just changed" are expressed.
                    </p>
                    <textarea
                        rows={4}
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        placeholder="You are {{char}}. Speak in a terse, noir cadence..."
                        className="w-full bg-gray-900 border border-white/10 rounded-lg p-2.5 font-mono text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50 resize-none"
                    />
                    <div className="grid grid-cols-3 gap-2">
                        <input
                            type="number"
                            step="0.05"
                            min="0"
                            max="2"
                            value={temperature}
                            onChange={(e) => setTemperature(e.target.value)}
                            placeholder="Temperature"
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                        />
                        <input
                            type="number"
                            step="0.05"
                            min="0"
                            max="1"
                            value={topP}
                            onChange={(e) => setTopP(e.target.value)}
                            placeholder="Top P"
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                        />
                        <input
                            type="number"
                            step="32"
                            min="64"
                            max="4096"
                            value={maxTokens}
                            onChange={(e) => setMaxTokens(e.target.value)}
                            placeholder="Max tokens"
                            className="bg-gray-900 border border-white/10 rounded-lg px-2.5 py-1.5 text-3xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50"
                        />
                    </div>
                    <div className="flex items-center justify-between">
                        <label className="flex items-center gap-1.5 text-3xs text-gray-300 cursor-pointer">
                            <input
                                type="checkbox"
                                checked={activate}
                                onChange={(e) => setActivate(e.target.checked)}
                                className="accent-purple-500"
                            />
                            <span>Activate after saving</span>
                        </label>
                        <div className="flex items-center gap-1.5">
                            <button
                                type="button"
                                onClick={resetForm}
                                className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 text-3xs font-semibold"
                            >
                                Cancel
                            </button>
                            <button
                                type="button"
                                onClick={handleSave}
                                disabled={saving}
                                className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-3xs font-semibold disabled:opacity-50"
                            >
                                {saving ? 'Saving...' : editing ? 'Save Variant' : 'Create Variant'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
