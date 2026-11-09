import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Settings as SettingsIcon, RotateCcw, Save, Info, Server, Brain, Loader2, CheckCircle, XCircle, Volume2, Clock, RefreshCw, CheckCircle2, AlertTriangle, ChevronDown, ChevronUp, Sparkles, ArrowRight, Bot, Shield, Cpu, Sliders, Play, GitBranch, HelpCircle, Activity } from 'lucide-react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { settingsApi } from '../api/settingsApi';
import { useConfirmation } from '../store/confirmationStore';
import { useSettings, useUpdateSettings, GALLERY_VIEW_MODES } from '../store/settingsStore';
import { useGeneratorStore } from '../store/generatorStore';
import { useBranding, useSaveBranding } from '../hooks/useBranding';
import { useLLMProviderStatus, useLLMRouting, useLLMCatalog, useLLMRuntimeDefaults, useSetLLMDefault } from '../hooks/useLLMProviderStatus';
import useProvidersPageData from '../hooks/useProvidersPageData';
import React, { useCallback, useEffect, useRef } from 'react';


function SystemPromptsEditor() {
    const queryClient = useQueryClient();
    const { updateCategory } = useUpdateSettings();
    const { data: blocksData, isLoading } = useQuery({
        queryKey: ['system_prompts_blocks'],
        queryFn: () => settingsApi.getSystemPrompts(),
        staleTime: 30000,
    });
    const [draft, setDraft] = useState({});
    const [saving, setSaving] = useState(false);
    const [showCharGen, setShowCharGen] = useState(false);
    // Seed once per mount. `refetchOnReconnect` is a global default, so a
    // reconnect mid-typing used to replace every textarea with the server copy
    // and silently discard the edit in progress.
    const seededDraftRef = useRef(false);

    useEffect(() => {
        if (seededDraftRef.current || !blocksData?.blocks) return;
        seededDraftRef.current = true;
        setDraft({ ...blocksData.blocks });
    }, [blocksData]);

    const handleSave = async () => {
        setSaving(true);
        try {
            await settingsApi.updateSystemPrompts({ blocks: draft });
            // Sync with local Zustand store for backward compatibility
            if (updateCategory) {
                updateCategory('ai', { ...draft });
            }
            toast.success('System prompts updated in config.json');
            queryClient.invalidateQueries({ queryKey: ['system_prompts_blocks'] });
        } catch {
            toast.error('Failed to save system prompts');
        } finally {
            setSaving(false);
        }
    };

    const coreFields = [
        { key: 'roleplay_default', label: 'Roleplay Default', desc: 'Default instructions used in every chat reply (before character prompt). Clear to disable.' },
        { key: 'narrator', label: 'Narrator Prompt', desc: 'Prompt used for narration scenes (narrate_scene tool and /narrate mode).' },
        { key: 'suggest_instruction', label: 'Suggest Instruction', desc: 'Instructions appended when suggesting user replies (/suggest).' },
    ];

    const charGenFields = [
        { key: 'charGenDescriptionPrompt', label: 'Description Prompt', desc: 'System prompt for generating character description' },
        { key: 'charGenPersonalityPrompt', label: 'Personality Prompt', desc: 'System prompt for generating character personality' },
        { key: 'charGenScenarioPrompt', label: 'Scenario Prompt', desc: 'System prompt for generating character scenario' },
        { key: 'charGenFirstMesPrompt', label: 'First Message Prompt', desc: 'System prompt for generating character first greeting message' },
        { key: 'charGenMesExamplePrompt', label: 'Message Examples Prompt', desc: 'System prompt for generating character dialogue examples' },
        { key: 'charGenSystemPromptPrompt', label: 'Character System Prompt', desc: 'System prompt for generating the character instruction block' },
        { key: 'charGenVisualTagsPrompt', label: 'Visual Tags Prompt', desc: 'System prompt for generating Danbooru-style appearance tags' },
        { key: 'charGenEnrichPrompt', label: 'Profile Enrichment Prompt', desc: 'System prompt for generating and enriching full character JSON profile' },
    ];

    if (isLoading) return <div className="text-xs text-gray-500">Loading prompts…</div>;

    return (
        <SettingGroup title="System Prompt Blocks" description="These blocks make up the assembled LLM prompt. Edit and save to update the server's config.json directly.">
            <div className="space-y-4">
                {coreFields.map(f => (
                    <div key={f.key}>
                        <label htmlFor={`prompt-block-${f.key}`} className="block text-xs font-bold uppercase tracking-widest text-gray-500 mb-1">{f.label}</label>
                        <p className="text-xs text-gray-600 mb-1">{f.desc}</p>
                        <textarea
                            id={`prompt-block-${f.key}`}
                            value={draft[f.key] || ''}
                            onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                            rows={4}
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-300 focus:outline-none focus:border-blue-500 resize-y min-h-[60px] font-sans"
                        />
                    </div>
                ))}

                {/* Character Generation Prompts Accordion */}
                <div className="pt-2 border-t border-white/5">
                    <button
                        type="button"
                        onClick={() => setShowCharGen(!showCharGen)}
                        className="flex items-center justify-between w-full py-2 text-left group"
                    >
                        <div className="flex items-center gap-2">
                            <Sparkles size={14} className="text-purple-400" />
                            <span className="text-xs font-bold text-gray-300 uppercase tracking-wider group-hover:text-white transition-colors">
                                Character Generator Prompts ({charGenFields.length})
                            </span>
                        </div>
                        {showCharGen ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                    </button>

                    {showCharGen && (
                        <div className="space-y-4 mt-3 pl-2 border-l border-purple-500/20">
                            {charGenFields.map(f => (
                                <div key={f.key}>
                                    <label htmlFor={`prompt-block-${f.key}`} className="block text-xs font-bold uppercase tracking-widest text-purple-300/80 mb-1">{f.label}</label>
                                    <p className="text-xs text-gray-600 mb-1">{f.desc}</p>
                                    <textarea
                                        id={`prompt-block-${f.key}`}
                                        value={draft[f.key] || ''}
                                        onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                                        rows={3}
                                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-300 focus:outline-none focus:border-purple-500 resize-y min-h-[50px] font-sans"
                                    />
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
            <div className="mt-4 flex justify-end">
                <button
                    onClick={handleSave}
                    disabled={saving || isLoading}
                    className="btn-primary px-4 py-2 text-xs flex items-center gap-2"
                >
                    {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                    Save prompts to server
                </button>
            </div>
        </SettingGroup>
    );
}

export default function Settings() {
    const settings = useSettings();
    const { updateSetting, updateCategory, resetCategory, resetSettings } = useUpdateSettings();
    const { confirm } = useConfirmation();
    const queryClient = useQueryClient();

    const [activeTab, setActiveTab] = useState('ui');
    const [resetting, setResetting] = useState(false);

    // `generator.default_checkpoint` and `generator.prompt_shortcuts` live on
    // the server; the local store keys are mirrors (ChatWorkspaceContext sends
    // default_checkpoint per message as `generator_checkpoint`). Keeping the
    // mirrors in step here means any path that writes the category — including
    // the Generator tab's Reset — cannot leave them stale.
    const handleMirroredGeneratorSettings = useCallback((settings) => {
        if (updateSetting && settings) {
            updateSetting('generator', 'defaultCheckpoint', settings.generator?.default_checkpoint || null);
            updateSetting('generator', 'prompt_shortcuts', settings.generator?.prompt_shortcuts || {});
            const liveEnabled = settings.generator?.live_preview ?? (settings.generator?.preview_method !== 'none');
            updateSetting('generator', 'live_preview_enabled', liveEnabled);
            updateSetting('generator', 'preview_method', settings.generator?.preview_method || (liveEnabled ? 'auto' : 'none'));
        }
    }, [updateSetting]);

    const handleUpdateSetting = async (category, key, value) => {
        updateSetting(category, key, value);
        if (category === 'generator' && (key === 'live_preview' || key === 'preview_method' || key === 'live_preview_enabled')) {
            try {
                const patch = key === 'live_preview_enabled'
                    ? { live_preview: Boolean(value), preview_method: value ? 'auto' : 'none' }
                    : { [key]: value };
                await settingsApi.update({ generator: patch });
                await queryClient.invalidateQueries({ queryKey: SETTINGS_CONFIG_QUERY_KEY });
            } catch (err) {
                toast.error(`Failed to update server setting: ${err?.message || err}`);
                return;
            }
        }
        toast.success('Setting updated!');
    };

    // Stable, so the AI tab's backend-seed effect keeps its mount-only deps and
    // does not re-seed (and re-write the whole category) on every render.
    const handleSyncAiSettings = useCallback((patch) => updateCategory('ai', patch), [updateCategory]);

    const handleResetCategory = (category) => {
        resetCategory(category);
        toast.success(`${category.toUpperCase()} settings reset to defaults`, { icon: '↩️' });
    };

    // "Reset All" used to call the Zustand store only, which cleared
    // localStorage and left config.json untouched — so the job limits, retry
    // policy and image-processing values the backend actually reads survived it
    // while the UI claimed everything was back to defaults. POST
    // /api/settings/reset exists and was fully implemented with no caller.
    const handleResetAll = async () => {
        const confirmed = await confirm({
            title: 'Reset All Settings',
            message:
                'This restores the BACKEND config.json to its compiled-in defaults — job concurrency, timeouts, retries, image processing, API, generator and AI settings — and clears this browser\'s UI preferences. Settings overridden by a COMFY_* environment variable are not affected, because the variable keeps winning. This cannot be undone.',
            confirmText: 'Reset Backend Config',
            isDangerous: true
        });
        if (!confirmed) return;
        setResetting(true);
        try {
            await settingsApi.reset();
            resetSettings();
            await queryClient.invalidateQueries({ queryKey: SETTINGS_CONFIG_QUERY_KEY });
            toast.success('Backend config and local preferences reset to defaults', { icon: '↩️' });
        } catch {
            toast.error('Failed to reset backend settings — nothing was changed locally');
        } finally {
            setResetting(false);
        }
    };

    const tabs = [
        { id: 'ai', label: 'AI / LLM', icon: Brain },
        { id: 'branding', label: 'Branding', icon: SettingsIcon },
        { id: 'ui', label: 'UI / UX', icon: SettingsIcon },
        { id: 'gallery', label: 'Gallery', icon: SettingsIcon },
        { id: 'models', label: 'Models', icon: SettingsIcon },
        { id: 'generator', label: 'Generator', icon: SettingsIcon },
        { id: 'backend', label: 'Backend', icon: Server },
    ];


    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="w-full"
        >
            <div className="max-w-6xl mx-auto space-y-4 md:space-y-8">
                {/* Header */}
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 glass-panel p-4 md:p-6 rounded-3xl border border-white/5 shadow-2xl">
                    <div className="flex items-center gap-5">
                        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 shadow-inner">
                            <SettingsIcon className="text-blue-400 drop-shadow-[0_0_10px_rgba(59,130,246,0.5)]" size={32} />
                        </div>
                        <div>
                            <h1 className="text-2xl md:text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 tracking-tight drop-shadow-md">
                                Settings
                            </h1>
                            <p className="text-gray-400 font-medium tracking-wide mt-1">Customize your ComfyUI experience</p>
                        </div>
                    </div>

                    <button
                        onClick={handleResetAll}
                        disabled={resetting}
                        className="px-6 py-3 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 hover:border-red-500/40 rounded-xl text-red-400 hover:text-red-300 font-bold tracking-wide flex items-center gap-3 transition-all duration-300 shadow-inner group disabled:opacity-50"
                    >
                        <RotateCcw size={20} className="group-hover:-rotate-180 transition-transform duration-500" />
                        {resetting ? 'Resetting…' : 'Reset All'}
                    </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
                    {/* Sidebar Tabs */}
                    <div className="md:col-span-3 space-y-2 glass-panel p-4 rounded-3xl border border-white/5 shadow-2xl h-fit sticky top-8">
                        <div className="px-4 py-2 mb-2 text-xs font-bold uppercase tracking-widest text-gray-500">Categories</div>
                        {tabs.map(tab => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={`w-full flex items-center gap-4 px-5 py-4 rounded-2xl font-bold tracking-wide transition-all duration-300 shadow-inner ${activeTab === tab.id
                                    ? 'bg-gradient-to-r from-blue-600/20 to-violet-600/20 border border-blue-500/30 text-white shadow-[0_0_15px_rgba(59,130,246,0.1)]'
                                    : 'bg-white/5 border border-transparent text-gray-400 hover:bg-white/10 hover:text-white'
                                    }`}
                            >
                                <tab.icon size={20} className={activeTab === tab.id ? 'text-blue-400' : 'text-gray-500'} />
                                {tab.label}
                            </button>
                        ))}
                    </div>

                    {/* Content Area */}
                    <div className="md:col-span-9 glass-panel rounded-3xl border border-white/5 shadow-2xl p-8 min-h-[60vh]">
                        {activeTab === 'ai' && (
                            <AISettings
                                settings={settings.ai}
                                onUpdate={(key, value) => handleUpdateSetting('ai', key, value)}
                                onSync={handleSyncAiSettings}
                                onReset={() => handleResetCategory('ai')}
                            />
                        )}

                        {activeTab === 'branding' && (<BrandingSettings />)}

                        {activeTab === 'ui' && (
                            <UISettings
                                settings={settings.ui}
                                onUpdate={(key, value) => handleUpdateSetting('ui', key, value)}
                                onReset={() => handleResetCategory('ui')}
                            />
                        )}

                        {activeTab === 'gallery' && (
                            <GallerySettings
                                settings={settings.gallery}
                                onUpdate={(key, value) => handleUpdateSetting('gallery', key, value)}
                                onReset={() => handleResetCategory('gallery')}
                            />
                        )}

                        {activeTab === 'models' && (
                            <ModelsSettings
                                settings={settings.models}
                                onUpdate={(key, value) => handleUpdateSetting('models', key, value)}
                                onReset={() => handleResetCategory('models')}
                            />
                        )}

                        {activeTab === 'generator' && (
                            <GeneratorSettings
                                settings={settings.generator}
                                onUpdate={(key, value) => handleUpdateSetting('generator', key, value)}
                                onReset={() => handleResetCategory('generator')}
                                onMirrorDefaultCheckpoint={handleMirroredGeneratorSettings}
                            />
                        )}

                        {activeTab === 'backend' && (
                            <BackendSettings onMirroredGeneratorSettings={handleMirroredGeneratorSettings} />
                        )}
                    </div>
                </div>
            </div>
        </motion.div>
    );
}

// ============================================================================
// SERVER-SIDE CONFIG (config.json via /api/settings)
// ============================================================================
// Server data lives in React Query, not the Zustand store: everything below
// reads config.json through these queries and writes it with the same
// PUT /api/settings the AI tab already used, so the backend job runner and the
// UI cannot disagree about what is configured.

const SETTINGS_CONFIG_QUERY_KEY = ['settings_config'];
const SETTINGS_SCHEMA_QUERY_KEY = ['settings_schema'];

function getConfigPath(object, path) {
    return path.split('.').reduce((node, part) => (node == null ? node : node[part]), object);
}

function setConfigPath(target, path, value) {
    const parts = path.split('.');
    let node = target;
    parts.forEach((part, index) => {
        if (index === parts.length - 1) {
            node[part] = value;
        } else {
            if (typeof node[part] !== 'object' || node[part] === null) node[part] = {};
            node = node[part];
        }
    });
    return target;
}

function useSettingsConfig() {
    return useQuery({
        queryKey: SETTINGS_CONFIG_QUERY_KEY,
        queryFn: () => settingsApi.get(),
        staleTime: 30000,
    });
}

function useSettingsSchema() {
    return useQuery({
        queryKey: SETTINGS_SCHEMA_QUERY_KEY,
        queryFn: () => settingsApi.getSchema(),
        staleTime: 5 * 60 * 1000,
    });
}

// Groups of server-backed settings, keyed by the config section they live in.
// The per-field type, bounds, default, env-var and restart annotations all come
// from GET /api/settings/schema, so these lists only say which controls exist
// and what to call them.
const BACKEND_GROUPS = [
    {
        section: 'jobs',
        title: 'Job Limits',
        description: 'How much work the backend keeps in flight, and how long it waits before giving up',
        fields: [
            { key: 'max_concurrent', label: 'Max Concurrent Jobs', hint: 'The spend throttle. Applies per task type, and is capped by your enabled provider count.' },
            { key: 'timeout', label: 'Job Timeout (s)', hint: 'Keep at or above the provider worker timeout, or the backend abandons work that is still running.' },
            { key: 'max_retries', label: 'Max Retries', hint: 'Automatic retries after a failed attempt' },
            { key: 'retry_base_delay', label: 'Retry Base Delay (s)', hint: 'First backoff step' },
            { key: 'retry_max_delay', label: 'Retry Max Delay (s)', hint: 'Backoff ceiling' },
        ],
    },
    {
        section: 'jobs',
        title: 'LLM Job Settings',
        description: 'Overrides applied to LLM jobs only, on top of the job limits above',
        fields: [
            { key: 'llm.timeout', label: 'LLM Timeout (s)' },
            { key: 'llm.max_retries', label: 'LLM Max Retries' },
            { key: 'llm.stagger_delay', label: 'Failover Stagger (s)', hint: 'Pace between LLM provider failover attempts' },
        ],
    },
    {
        section: 'image_processing',
        title: 'Image Processing',
        description: 'Thumbnails and output files',
        fields: [
            { key: 'thumbnail_quality', label: 'Thumbnail Quality', hint: 'Encoder quality for generated thumbnails' },
            { key: 'output_date_hierarchy', label: 'Date Folder Hierarchy', hint: 'Write outputs into YYYY/MM/DD folders instead of one flat directory' },
            { key: 'embed_metadata_in_png', label: 'Embed Generation Metadata', hint: 'Write generation parameters into the output file' },
        ],
    },
    {
        section: 'generator',
        title: 'Image Generator Defaults',
        description: 'Server defaults and live preview performance policy for image generation',
        fields: [
            { key: 'preview_method', label: 'Preview Method', hint: "'auto' for live progressive preview in job card, 'none' for maximum generation speed" },
            { key: 'live_preview', label: 'Live Latent Preview Enabled', hint: 'Stream intermediate generation previews to the gallery' },
        ],
    },
    {
        section: 'roleplay',
        title: 'Roleplay Turn Formatting',
        description: 'How messages become LLM turns during story and character conversation generation',
        fields: [
            { key: 'label_speakers', label: 'Label Speakers', hint: 'Prefix each speaking turn with the character name' },
            { key: 'narrator_prefix', label: 'Narrator Prefix', hint: 'Prefix for narration turns (e.g. [Narration])' },
            { key: 'image_prefix', label: 'Image Prefix', hint: 'Prefix for illustration turns (e.g. [Scene])' },
        ],
    },
    {
        section: 'jobs_cleanup',
        title: 'Job History Cleanup',
        description: 'Automatic housekeeping of completed and failed inference jobs',
        fields: [
            { key: 'auto_cleanup', label: 'Auto Cleanup Enabled', hint: 'Periodically remove old job records from the database' },
            { key: 'max_age_hours', label: 'Max Job Age (hours)', hint: 'Jobs older than this will be pruned' },
            { key: 'cleanup_interval', label: 'Cleanup Interval (s)', hint: 'Interval between auto-cleanup runs in seconds' },
        ],
    },
    {
        section: 'api',
        title: 'API Server',
        description: 'Bound once at startup, so changes here only take effect after a backend restart',
        fields: [
            { key: 'cors_origins', label: 'CORS Origins', hint: 'Comma-separated list of allowed origins' },
            { key: 'gzip_minimum_size', label: 'GZip Minimum Size (bytes)' },
        ],
    },
];

function RestartBadge() {
    return (
        <span className="px-2 py-0.5 rounded bg-amber-500/15 border border-amber-500/30 text-amber-300 text-2xs font-bold uppercase tracking-wider">
            Restart required
        </span>
    );
}

function EnvOverrideBadge({ envVar }) {
    return (
        <span className="px-2 py-0.5 rounded bg-purple-500/15 border border-purple-500/30 text-purple-300 text-2xs font-bold uppercase tracking-wider">
            Overridden by {envVar}
        </span>
    );
}

function ServerConfigControl({ field, spec, value, onChange, envVar, disabled }) {
    const locked = Boolean(envVar);
    const hint = locked
        ? `Set by ${envVar} in this backend's environment. The config file value is ignored while it is present, so this control is read-only.`
        : spec.restart_required
            ? 'Read at backend startup — saving here only stages the value for the next restart.'
            : field.hint;
    const badges = [
        ...(locked ? [<EnvOverrideBadge key="env" envVar={envVar} />] : []),
        ...(spec.restart_required ? [<RestartBadge key="restart" />] : []),
    ];

    let control;
    if (spec.type === 'boolean') {
        control = (
            <label className="flex items-center gap-4 cursor-pointer group">
                <div className="relative">
                    <input
                        type="checkbox"
                        checked={Boolean(value)}
                        disabled={locked || disabled}
                        onChange={(e) => onChange(e.target.checked)}
                        className="sr-only peer disabled:opacity-50"
                    />
                    <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                </div>
                <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">
                    {value ? 'Enabled' : 'Disabled'}
                </span>
            </label>
        );
    } else if (spec.type === 'array') {
        control = (
            <input
                type="text"
                value={Array.isArray(value) ? value.join(', ') : ''}
                disabled={locked || disabled}
                onChange={(e) => onChange(e.target.value.split(',').map((origin) => origin.trim()).filter(Boolean))}
                placeholder="http://localhost:5174, https://example.test"
                className="w-full md:w-96 bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 text-white text-sm font-medium focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus outline-none disabled:opacity-60"
            />
        );
    } else {
        const numeric = spec.type === 'integer' || spec.type === 'number';
        control = (
            <input
                type={numeric ? 'number' : 'text'}
                min={numeric ? spec.min : undefined}
                max={numeric ? spec.max : undefined}
                step={spec.type === 'integer' ? 1 : numeric ? 0.1 : undefined}
                value={value ?? ''}
                disabled={locked || disabled}
                onChange={(e) => onChange(numeric ? Number(e.target.value) : e.target.value)}
                className="w-32 bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 text-white font-medium focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus outline-none disabled:opacity-60"
            />
        );
    }

    return (
        <SettingGroup
            title={field.label}
            description={hint}
            action={badges.length ? <div className="flex items-center gap-2">{badges}</div> : null}
        >
            {control}
        </SettingGroup>
    );
}

function BackendSettings({ onMirroredGeneratorSettings }) {
    const queryClient = useQueryClient();
    const { data: configResponse, isLoading } = useSettingsConfig();
    const { data: schemaResponse } = useSettingsSchema();
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const [saveState, setSaveState] = useState('idle');

    // Seed the draft from the server config, and mirror generator settings
    // (default_checkpoint, prompt_shortcuts) into the local store so the
    // generator page can read them.
    useEffect(() => {
        const settings = configResponse?.settings;
        if (!settings) return;
        setDraft(settings);
        if (onMirroredGeneratorSettings) {
            onMirroredGeneratorSettings(settings);
        }
    }, [configResponse, onMirroredGeneratorSettings]);

    const envOverrides = schemaResponse?.env_overrides || {};

    const handleSave = async () => {
        const payload = {};
        const skipped = [];
        for (const group of BACKEND_GROUPS) {
            for (const field of group.fields) {
                const path = `${group.section}.${field.key}`;
                if (envOverrides[path]) {
                    skipped.push(field.label);
                    continue;
                }
                setConfigPath(payload, `${group.section}.${field.key}`, getConfigPath(draft, `${group.section}.${field.key}`));
            }
        }
        setSaving(true);
        try {
            await settingsApi.update(payload);
            setSaveState('saved');
            await queryClient.invalidateQueries({ queryKey: SETTINGS_CONFIG_QUERY_KEY });
            const suffix = skipped.length ? ` (${skipped.join(', ')} kept ${skipped.length === 1 ? 'its' : 'their'} env override)` : '';
            toast.success(`Backend settings saved${suffix}`);
        } catch (error) {
            setSaveState('idle');
            toast.error(error?.message ? `Rejected: ${error.message}` : 'Failed to save backend settings');
        } finally {
            setSaving(false);
        }
    };

    if (isLoading || !draft) {
        return (
            <div className="flex flex-col items-center justify-center h-48 space-y-4">
                <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
                <div className="text-sm font-bold tracking-widest uppercase text-gray-500">Loading backend config…</div>
            </div>
        );
    }

    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-end gap-4 pb-6 border-b border-white/5">
                <div>
                    <h2 className="text-2xl font-bold tracking-wide text-white">Backend Settings</h2>
                    <p className="text-sm font-medium text-gray-400 mt-2">
                        Written to the server&apos;s config.json and read by the job runner, image pipeline and API — not just this browser.
                    </p>
                </div>
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 border border-white/10 rounded-xl text-white font-bold tracking-wide flex items-center gap-2 disabled:opacity-50 transition-all duration-300 shadow-lg"
                >
                    {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    {saveState === 'saved' ? 'Saved' : 'Save to backend'}
                </button>
            </div>

            <div className="bg-blue-500/10 border border-blue-500/30 rounded-2xl p-5 flex items-start gap-4 shadow-inner">
                <div className="bg-blue-500/20 p-2 rounded-xl flex-shrink-0">
                    <Info className="text-blue-400" size={20} />
                </div>
                <div>
                    <p className="font-bold tracking-wide text-blue-400 mb-1 text-sm uppercase">These are server values</p>
                    <p className="text-sm text-gray-300 font-medium leading-relaxed">
                        Changes take effect for the next request. Fields controlled by a <code className="text-purple-300 bg-purple-500/10 px-1.5 py-0.5 rounded border border-purple-500/20">COMFY_*</code> environment
                        variable are shown read-only, because the variable keeps winning over this file.
                    </p>
                </div>
            </div>

            <div className="grid gap-6">
                {BACKEND_GROUPS.map(group => (
                    <div key={`${group.section}-${group.title}`} className="border border-white/5 rounded-2xl bg-white/5 shadow-inner p-5">
                        <h3 className="font-bold text-white tracking-wide">{group.title}</h3>
                        <p className="text-sm font-medium text-gray-400 mt-1 mb-2">{group.description}</p>
                        {group.fields.map(field => {
                            const spec = schemaResponse?.schema?.[group.section]?.fields?.[field.key];
                            if (!spec) {
                                return (
                                    <div key={field.key} className="py-4 border-b border-white/5 text-xs text-amber-300">
                                        {field.label}: not documented by the backend schema — control hidden.
                                    </div>
                                );
                            }
                            const path = `${group.section}.${field.key}`;
                            return (
                                <ServerConfigControl
                                    key={field.key}
                                    field={field}
                                    spec={spec}
                                    envVar={envOverrides[path]}
                                    value={getConfigPath(draft, `${group.section}.${field.key}`)}
                                    onChange={(next) => setDraft((current) => setConfigPath({ ...current }, `${group.section}.${field.key}`, next))}
                                />
                            );
                        })}
                    </div>
                ))}
            </div>

            {/* Scheduled Background Tasks Dashboard */}
            <ScheduledTasksPanel />

            {/* Data Integrity & Lost Artifact Recovery */}
            <DataIntegrityPanel />
        </div>
    );
}

function ScheduledTasksPanel() {
    const { data, isLoading, isError, refetch, isFetching } = useQuery({
        queryKey: ['scheduler_status'],
        queryFn: () => settingsApi.getSchedulerStatus(),
        refetchInterval: 15000,
    });

    const jobs = data?.jobs || [];

    const formatTime = (iso) => {
        if (!iso) return 'Never';
        try {
            const d = new Date(iso);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch {
            return iso;
        }
    };

    const statusBadge = (status) => {
        switch (status) {
            case 'success':
                return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-emerald-500/15 border border-emerald-500/30 text-emerald-400"><CheckCircle2 size={10} /> Success</span>;
            case 'failed':
                return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-red-500/15 border border-red-500/30 text-red-400"><AlertTriangle size={10} /> Failed</span>;
            case 'skipped':
                return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-amber-500/15 border border-amber-500/30 text-amber-300">Skipped (Locked)</span>;
            default:
                return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider bg-gray-500/15 border border-gray-500/30 text-gray-400">Idle / Pending</span>;
        }
    };

    return (
        <div className="border border-white/5 rounded-2xl bg-white/5 shadow-inner p-5 space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="font-bold text-white tracking-wide flex items-center gap-2">
                        <Clock size={18} className="text-blue-400" />
                        Scheduled Background Tasks
                    </h3>
                    <p className="text-sm font-medium text-gray-400 mt-1">
                        Active APScheduler recurring jobs running across backend worker threads
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <Link
                        to="/tasks"
                        className="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 rounded-xl text-xs font-semibold text-blue-400 flex items-center gap-1.5 transition-colors"
                    >
                        Full Control Center <ArrowRight size={12} />
                    </Link>
                    <button
                        onClick={() => refetch()}
                        disabled={isFetching}
                        aria-label="Refresh scheduler status"
                        className="px-3 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-xs font-semibold text-gray-300 flex items-center gap-1.5 transition-colors disabled:opacity-50"
                        title="Refresh scheduler status"
                    >
                        <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} />
                        Refresh
                    </button>
                </div>
            </div>

            {isLoading ? (
                <div className="flex items-center gap-2 text-xs text-gray-400 py-4">
                    <Loader2 size={14} className="animate-spin text-blue-400" />
                    Inspecting running tasks…
                </div>
            ) : isError ? (
                <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-xl text-xs text-red-400">
                    Failed to query scheduler status.
                </div>
            ) : jobs.length === 0 ? (
                <div className="text-xs text-gray-500 py-2">No scheduled jobs registered.</div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                        <thead>
                            <tr className="border-b border-white/10 text-gray-400 uppercase tracking-wider font-semibold">
                                <th className="pb-2.5">Job ID</th>
                                <th className="pb-2.5">Schedule</th>
                                <th className="pb-2.5">Next Run</th>
                                <th className="pb-2.5">Last Status</th>
                                <th className="pb-2.5">Last Duration</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                            {jobs.map((job) => (
                                <tr key={job.id} className="hover:bg-white/[0.02]">
                                    <td className="py-2.5 font-mono text-purple-300 font-semibold">{job.id}</td>
                                    <td className="py-2.5 text-gray-300 font-mono text-2xs">{job.trigger}</td>
                                    <td className="py-2.5 text-gray-400">{formatTime(job.next_run)}</td>
                                    <td className="py-2.5">{statusBadge(job.last_status)}</td>
                                    <td className="py-2.5 text-gray-400 font-mono">
                                        {job.last_duration_seconds != null ? `${job.last_duration_seconds}s` : '—'}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

function DataIntegrityPanel() {
    const [reconciling, setReconciling] = useState(false);

    const handleReconcile = async () => {
        setReconciling(true);
        try {
            const res = await settingsApi.reconcileChatReplies({ dry_run: false });
            const recovered = res?.reconciled_count ?? res?.count ?? 0;
            toast.success(`Integrity check complete: ${recovered} dropped chat artifact(s) recovered!`);
        } catch (err) {
            toast.error(err?.message ? `Reconciliation failed: ${err.message}` : 'Failed to reconcile chat artifacts');
        } finally {
            setReconciling(false);
        }
    };

    return (
        <div className="border border-white/5 rounded-2xl bg-white/5 shadow-inner p-5 space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h3 className="font-bold text-white tracking-wide flex items-center gap-2">
                        <RotateCcw size={18} className="text-emerald-400" />
                        Lost Artifact Recovery
                    </h3>
                    <p className="text-sm font-medium text-gray-400 mt-1">
                        Find and recover paid chat replies, scene narrations, or story illustrations whose worker events were dropped under queue pressure.
                    </p>
                </div>
                <button
                    onClick={handleReconcile}
                    disabled={reconciling}
                    className="px-4 py-2 bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/30 rounded-xl text-emerald-300 text-xs font-bold tracking-wide flex items-center gap-2 transition-all disabled:opacity-50 shrink-0"
                >
                    {reconciling ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />}
                    Recover Dropped Artifacts
                </button>
            </div>
        </div>
    );
}

// Branding Settings Component
function BrandingSettings() {
    const { data: branding, isLoading } = useBranding();
    const saveBranding = useSaveBranding();
    const [localBranding, setLocalBranding] = useState(null);

    const effectiveBranding = localBranding || branding;

    const handleSave = async () => {
        try {
            await saveBranding.mutateAsync(effectiveBranding);
            setLocalBranding(null);
            toast.success('Branding updated! Refresh the page to see changes.');
        } catch {
            toast.error('Failed to save branding settings');
        }
    };

    const handleReset = async () => {
        const defaultBranding = {
            appName: "TNH-Comfy",
            logoUrl: "/logo.png",
            faviconUrl: "/favicon.ico"
        };
        try {
            await saveBranding.mutateAsync(defaultBranding);
            setLocalBranding(null);
            toast.success('Branding reset to defaults. Refresh the page to see changes.');
        } catch {
            toast.error('Failed to reset branding settings');
        }
    };

    if (isLoading || !effectiveBranding) {
        return (
            <div className="flex flex-col items-center justify-center h-48 space-y-4">
                <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
                <div className="text-sm font-bold tracking-widest uppercase text-gray-500">Loading branding...</div>
            </div>
        );
    }

    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-end gap-4 pb-6 border-b border-white/5">
                <div>
                    <h2 className="text-2xl font-bold tracking-wide text-white">Branding</h2>
                    <p className="text-sm font-medium text-gray-400 mt-2">
                        Customize your app's name and logo. Refresh the page after saving to see changes.
                    </p>
                </div>
                <div className="flex gap-3">
                    <button
                        onClick={handleReset}
                        className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner"
                    >
                        <RotateCcw size={16} /> Reset
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={isLoading}
                        className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 border border-white/10 rounded-xl text-white font-bold tracking-wide flex items-center gap-2 disabled:opacity-50 transition-all duration-300 shadow-lg hover:shadow-[0_0_15px_rgba(59,130,246,0.4)] transform active:scale-95"
                    >
                        <Save size={18} />
                        {isLoading ? 'Saving...' : 'Save'}
                    </button>
                </div>
            </div>

            <div className="grid gap-6">
                {/* App Name */}
                <SettingGroup title="App Name" description="The name displayed in the browser tab and sidebar">
                    <input
                        type="text"
                        value={effectiveBranding.appName}
                        onChange={(e) => setLocalBranding({ ...effectiveBranding, appName: e.target.value })}
                        className="w-full md:w-96 bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3.5 text-white font-medium focus:ring-2 focus:ring-blue-500/50 outline-none shadow-inner glow-focus transition-all"
                        placeholder="Enter app name"
                    />
                </SettingGroup>

                <div className="h-px w-full bg-gradient-to-r from-transparent via-white/5 to-transparent my-2" />

                {/* Logo Preview */}
                <SettingGroup title="App Logo" description="The logo image displayed in the sidebar">
                    <div className="flex items-center gap-6 glass-panel p-5 rounded-2xl border border-white/5 shadow-inner">
                        <div className="w-20 h-20 bg-[#0B0E14] rounded-xl border border-white/10 flex items-center justify-center p-3 shadow-inner relative group overflow-hidden">
                            <div className="absolute inset-0 bg-blue-500/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                            <img
                                src={effectiveBranding.logoUrl}
                                alt="Logo Preview"
                                className="w-full h-full object-contain drop-shadow-[0_0_10px_rgba(255,255,255,0.1)] relative z-10"
                                onError={(e) => {
                                    e.target.src = '/logo.png';
                                }}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-bold uppercase tracking-widest text-gray-500">Current</span>
                                <span className="text-sm font-medium text-gray-300 bg-white/5 px-2.5 py-1 rounded-lg border border-white/5">{effectiveBranding.logoUrl}</span>
                            </div>
                            <p className="text-xs text-gray-400 font-medium">To change: upload a new file to <code className="text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded border border-blue-500/20">/frontend/public/logo.png</code></p>
                        </div>
                    </div>
                </SettingGroup>

                {/* Favicon Info */}
                <SettingGroup title="Browser Favicon" description="The tiny icon displayed in your browser tab">
                    <div className="flex items-center gap-6 glass-panel p-5 rounded-2xl border border-white/5 shadow-inner">
                        <div className="w-12 h-12 bg-[#0B0E14] rounded-xl border border-white/10 flex items-center justify-center p-2 shadow-inner relative group overflow-hidden">
                            <div className="absolute inset-0 bg-purple-500/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                            <img
                                src={effectiveBranding.faviconUrl}
                                alt="Favicon Preview"
                                className="w-full h-full object-contain relative z-10"
                                onError={(e) => {
                                    e.target.src = '/favicon.ico';
                                }}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-bold uppercase tracking-widest text-gray-500">Current</span>
                                <span className="text-sm font-medium text-gray-300 bg-white/5 px-2.5 py-1 rounded-lg border border-white/5">{effectiveBranding.faviconUrl}</span>
                            </div>
                            <p className="text-xs text-gray-400 font-medium">To change: upload a new file to <code className="text-purple-400 bg-purple-500/10 px-1.5 py-0.5 rounded border border-purple-500/20">/frontend/public/favicon.ico</code></p>
                        </div>
                    </div>
                </SettingGroup>
            </div>

            <div className="bg-blue-500/10 border border-blue-500/30 rounded-2xl p-5 flex items-start gap-4 shadow-inner">
                <div className="bg-blue-500/20 p-2 rounded-xl flex-shrink-0">
                    <Info className="text-blue-400" size={20} />
                </div>
                <div>
                    <p className="font-bold tracking-wide text-blue-400 mb-1 text-sm uppercase">Live Preview</p>
                    <p className="text-sm text-gray-300 font-medium leading-relaxed">
                        Branding changes are applied automatically across the app within a few seconds.
                    </p>
                </div>
            </div>
        </div>
    );
}

// UI Settings Component
function UISettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">UI / UX Settings</h2>
                <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                {/* Default View Mode */}
                <SettingGroup title="Default View Mode" description="Choose the default view mode for the gallery">
                    <select
                        /* The value is coerced into the vocabulary before it
                           reaches the DOM. A `<select>` whose value has no
                           matching `<option>` renders *blank* — which is what
                           happened here: the live gallery mode and this
                           preference were the same key, the live mode could be
                           `session` (reachable from the Dashboard toggle, with
                           no option for it anywhere), and a user landing on this
                           select while in the session view saw an empty
                           dropdown. Deriving the options from the one
                           vocabulary also stops the two lists drifting again. */
                        value={
                            GALLERY_VIEW_MODES.includes(settings.defaultViewMode)
                                ? settings.defaultViewMode
                                : GALLERY_VIEW_MODES[0]
                        }
                        onChange={(e) => onUpdate('defaultViewMode', e.target.value)}
                        aria-label="Default view mode"
                        className="w-full lg:w-64 max-w-full min-w-0 bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 text-white font-medium focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus outline-none"
                    >
                        {GALLERY_VIEW_MODES.map((mode) => (
                            <option key={mode} value={mode}>
                                {mode.charAt(0).toUpperCase() + mode.slice(1)}
                            </option>
                        ))}
                    </select>
                </SettingGroup>

                {/* Default Grid Columns */}
                <SettingGroup title="Default Grid Columns" description="Number of columns in grid view">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Default gallery grid columns"
                            min="2"
                            max="8"
                            value={settings.defaultGridColumns}
                            onChange={(e) => onUpdate('defaultGridColumns', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-lg w-8 text-center bg-white/5 py-1 rounded-lg border border-white/5">{settings.defaultGridColumns}</span>
                    </div>
                </SettingGroup>

                {/* Toast Duration */}
                <SettingGroup
                    title="Toast Success Duration"
                    description="How long success toasts stay visible (milliseconds)"
                >
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Success toast duration"
                            min="1000"
                            max="10000"
                            step="500"
                            value={settings.toastSuccessDuration}
                            onChange={(e) => onUpdate('toastSuccessDuration', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-green-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.toastSuccessDuration}ms</span>
                    </div>
                </SettingGroup>

                <SettingGroup
                    title="Toast Error Duration"
                    description="How long error toasts stay visible (milliseconds)"
                >
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Error toast duration"
                            min="1000"
                            max="10000"
                            step="500"
                            value={settings.toastErrorDuration}
                            onChange={(e) => onUpdate('toastErrorDuration', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-red-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.toastErrorDuration}ms</span>
                    </div>
                </SettingGroup>

                {/* Animation Duration */}
                <SettingGroup title="Animation Duration" description="Speed of page transition and modal animations (milliseconds)">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Animation duration"
                            min="0"
                            max="500"
                            step="50"
                            value={settings.animationDuration}
                            onChange={(e) => onUpdate('animationDuration', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-purple-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.animationDuration}ms</span>
                    </div>
                </SettingGroup>

                {/* Query Cache Times */}
                <SettingGroup title="Data Stale Time" description="How long data is considered fresh before refetching (minutes)">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Query stale time"
                            min="1"
                            max="30"
                            value={settings.queryStaleTime / 60000}
                            onChange={(e) => onUpdate('queryStaleTime', parseInt(e.target.value) * 60000)}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.queryStaleTime / 60000} min</span>
                    </div>
                </SettingGroup>

                <SettingGroup title="Cache Time" description="How long data is kept in cache (minutes)">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Query cache time"
                            min="1"
                            max="60"
                            value={settings.queryCacheTime / 60000}
                            onChange={(e) => onUpdate('queryCacheTime', parseInt(e.target.value) * 60000)}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.queryCacheTime / 60000} min</span>
                    </div>
                </SettingGroup>
            </div>
        </div>
    );
}

// Gallery Settings Component
function GallerySettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">Gallery Settings</h2>
                <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                <SettingGroup title="Items Per Page" description="Number of items to load per page">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Items per page"
                            min="10"
                            max="100"
                            step="10"
                            value={settings.itemsPerPage}
                            onChange={(e) => onUpdate('itemsPerPage', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-16 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.itemsPerPage}</span>
                    </div>
                </SettingGroup>

                <SettingGroup title="Auto-Refresh on Job Complete" description="Automatically refresh gallery when a generation completes">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.autoRefreshOnJobComplete}
                                onChange={(e) => onUpdate('autoRefreshOnJobComplete', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.autoRefreshOnJobComplete ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>

                <SettingGroup title="Silent Refresh" description="Refresh without showing loading indicators">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.silentRefresh}
                                onChange={(e) => onUpdate('silentRefresh', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.silentRefresh ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>
            </div>
        </div>
    );
}

// Models Settings Component
function ModelsSettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">Model Manager Settings</h2>
                <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                <SettingGroup title="Items Per Page" description="Number of models to display per page">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Items per page"
                            min="10"
                            max="100"
                            step="10"
                            value={settings.itemsPerPage}
                            onChange={(e) => onUpdate('itemsPerPage', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-16 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.itemsPerPage}</span>
                    </div>
                </SettingGroup>

                {/* "Auto-Remove Downloads" lived here and was removed. It was the
                    one literally non-functional control in the codebase: a
                    labelled switch bound to `settings.autoRemoveDownloads`,
                    which persisted to localStorage and was read by nothing —
                    not here, not in any hook, not in the backend. The real
                    control is `downloads.auto_remove_delay` in config.json,
                    surfaced on the Providers tab, and it is a different
                    behaviour with a different name. Shipping a switch that
                    cannot do anything is worse than shipping no switch. */}
            </div>
        </div>
    );
}

import { useModelDirectories } from '../hooks/useModelDirectories';

// Default Checkpoint is a SERVER setting (`generator.default_checkpoint` in
// config.json), not a localStorage preference: services/job_processing.py,
// services/image_submission.py and services/model_availability_service.py all
// read it as the fallback when a request names no checkpoint. It used to be
// written to the Zustand store only, so the control silently did nothing to the
// value the backend actually used.
function ServerCheckpointSelect({ installed, loading, onMirror }) {
    const queryClient = useQueryClient();
    const { data: configResponse } = useSettingsConfig();
    const [saving, setSaving] = useState(false);

    const serverValue = configResponse?.settings?.generator?.default_checkpoint || '';
    const installedNames = installed.map((model) => (typeof model === 'string' ? model : model.filename));
    const notInstalled = Boolean(serverValue) && !installedNames.includes(serverValue);

    useEffect(() => {
        // The WHOLE settings object, not the checkpoint string. The mirror
        // callback reads `settings.generator?.default_checkpoint` and
        // `settings.generator?.prompt_shortcuts`; handed a string it saw
        // `undefined` for both and blanked the mirror - so opening this tab
        // deleted the generator's prompt shortcuts, and the store persisted
        // that to localStorage.
        if (onMirror) onMirror(configResponse?.settings);
    }, [configResponse, onMirror]);

    const handleChange = async (next) => {
        setSaving(true);
        try {
            await settingsApi.update({ generator: { default_checkpoint: next } });
            await queryClient.invalidateQueries({ queryKey: SETTINGS_CONFIG_QUERY_KEY });
            toast.success(next ? `Server default checkpoint set to ${next}` : 'Server default checkpoint cleared');
        } catch (error) {
            toast.error(error?.message ? `Rejected: ${error.message}` : 'Failed to set the default checkpoint');
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="w-full lg:max-w-md flex flex-col items-start lg:items-end">
            <select
                value={serverValue}
                onChange={(e) => handleChange(e.target.value)}
                className="w-full md:w-64 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-500 disabled:opacity-60"
                disabled={loading || saving}
            >
                <option value="">{'(unset — backend falls back to its compiled-in default)'}</option>
                {notInstalled && (
                    <option value={serverValue}>{`${serverValue} (not installed)`}</option>
                )}
                {installed.map(model => (
                    <option key={typeof model === 'string' ? model : model.filename} value={typeof model === 'string' ? model : model.filename}>
                        {typeof model === 'string' ? model : model.name || model.filename}
                    </option>
                ))}
            </select>
            {notInstalled && (
                <p className="mt-2 text-xs text-amber-300 text-left lg:text-right max-w-sm">
                    The configured checkpoint is not among the installed models, so generations fall back to it and will fail
                    until it is installed or a different one is selected.
                </p>
            )}
        </div>
    );
}

function ServerLivePreviewToggle({ onUpdate, localSetting }) {
    const queryClient = useQueryClient();
    const { data: configResponse, isLoading } = useSettingsConfig();
    const [saving, setSaving] = useState(false);

    const gen = configResponse?.settings?.generator || {};
    const previewMethod = gen.preview_method ?? (gen.live_preview === false ? 'none' : 'auto');
    const isLivePreview = Boolean(localSetting ?? (previewMethod !== 'none'));

    const handleToggle = async (e) => {
        const nextEnabled = e.target.checked;
        const nextMethod = nextEnabled ? 'auto' : 'none';
        setSaving(true);
        if (onUpdate) {
            onUpdate('live_preview_enabled', nextEnabled);
        }
        try {
            await settingsApi.update({
                generator: {
                    preview_method: nextMethod,
                    live_preview: nextEnabled,
                },
            });
            await queryClient.invalidateQueries({ queryKey: SETTINGS_CONFIG_QUERY_KEY });
            toast.success(
                nextEnabled
                    ? 'Live Latent Preview enabled (workers will restart ComfyUI with preview flags)'
                    : 'Max Speed enabled (workers will restart ComfyUI with --preview-method none)'
            );
        } catch (error) {
            toast.error(error?.message ? `Failed: ${error.message}` : 'Failed to update preview setting');
        } finally {
            setSaving(false);
        }
    };


    if (isLoading) {
        return <div className="text-xs text-gray-500">Loading preview setting...</div>;
    }

    return (
        <div className="space-y-2">
            <label className="flex items-center gap-4 cursor-pointer group">
                <div className="relative">
                    <input
                        type="checkbox"
                        checked={isLivePreview}
                        disabled={saving}
                        onChange={handleToggle}
                        className="sr-only peer"
                    />
                    <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                </div>
                <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">
                    {saving ? 'Updating...' : isLivePreview ? 'Live Latent Preview (TAESD)' : 'Max Speed (Preview Disabled)'}
                </span>
            </label>
            <p className="text-xs text-gray-500 max-w-xl">
                When enabled, intermediate latent frames stream into the gallery job card during sampling. When disabled, latent decoding overhead is bypassed for maximum generation speed. Remote workers will automatically sync this setting and restart ComfyUI with matching launch flags.
            </p>
        </div>
    );
}


// Generator Settings Component
function GeneratorSettings({ settings, onUpdate, onReset, onMirrorDefaultCheckpoint }) {
    // This one preference lives in the generator store rather than in
    // `settings`, because it is read inside `setSelectedCheckpoint` — the
    // action that decides whether to rewrite the sampler. Mirroring it into
    // `settings` would have meant two sources of truth for one switch, which is
    // how it ended up permanently `true` with no control anywhere in the UI:
    // the setter existed, the field persisted, and nothing rendered it.
    const autoApplyModelSettings = useGeneratorStore((state) => state.autoApplyModelSettings);
    const setAutoApplyModelSettings = useGeneratorStore((state) => state.setAutoApplyModelSettings);
    const { modelsByKey, loading } = useModelDirectories([{ directory: 'models/checkpoints', key: 'checkpoints' }]);
    const checkpoints = modelsByKey.checkpoints || [];
    const { data: configResponse } = useSettingsConfig();

    const handleReset = () => {
        onReset();
        // The checkpoint is server-owned, so restoring the local category
        // defaults must not blank its mirror in the store.
        if (onMirrorDefaultCheckpoint) {
            onMirrorDefaultCheckpoint(configResponse?.settings);
        }
    };

    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">Generator Settings</h2>
                <button onClick={handleReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                <SettingGroup
                    title="Default Checkpoint"
                    description="Server-side fallback used whenever a generation does not name a checkpoint (agentic image generation, story illustrations)"
                >
                    <ServerCheckpointSelect installed={checkpoints} loading={loading} onMirror={onMirrorDefaultCheckpoint} />
                </SettingGroup>
                <SettingGroup
                    title="Live Latent Preview vs Max Speed"
                    description="Toggle progressive latent preview rendering during generation or disable for peak generation speed"
                >
                    <ServerLivePreviewToggle onUpdate={onUpdate} localSetting={settings.live_preview_enabled} />
                </SettingGroup>


                <SettingGroup title="Auto-Randomize Seed" description="Automatically randomize seed after each generation">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.autoRandomizeSeed}
                                onChange={(e) => onUpdate('autoRandomizeSeed', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.autoRandomizeSeed ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>

                <SettingGroup
                    title="Auto-Apply Model Settings"
                    description="When you pick a checkpoint, load its recommended sampler settings (steps, CFG, sampler, scheduler, resolution, clip skip)"
                >
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={autoApplyModelSettings}
                                onChange={(e) => setAutoApplyModelSettings(e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{autoApplyModelSettings ? 'Enabled' : 'Disabled'}</span>
                    </label>
                    <p className="text-xs text-gray-500 mt-3 max-w-xl">
                        Selecting a checkpoint rewrites the values above with that model's recommended
                        ones, except anything you have locked. With this off, picking a checkpoint
                        leaves your sampler exactly as you set it. The switch existed in the store,
                        persisted, and had no control anywhere — so it was permanently{' '}
                        <span className="text-gray-400">on</span> with no way to turn it off.
                    </p>
                </SettingGroup>

                <SettingGroup title="Redirect After Generate" description="Redirect to gallery after starting generation">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.redirectAfterGenerate}
                                onChange={(e) => onUpdate('redirectAfterGenerate', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.redirectAfterGenerate ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>

                {settings.redirectAfterGenerate && (
                    <SettingGroup title="Redirect Delay" description="Delay before redirecting (milliseconds)">
                        <div className="flex items-center gap-5">
                            <input
                                type="range"
                            aria-label="Post-generation redirect delay"
                                min="0"
                                max="5000"
                                step="500"
                                value={settings.redirectDelay}
                                onChange={(e) => onUpdate('redirectDelay', parseInt(e.target.value))}
                                className="w-full md:w-64 accent-blue-500"
                            />
                            <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.redirectDelay}ms</span>
                        </div>
                    </SettingGroup>
                )}
            </div>
        </div>
    );
}

// Reusable Setting Group Component
function SettingGroup({ title, description, children, action }) {
    return (
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6 pb-6 border-b border-white/5 last:border-0 last:pb-0">
            {/* `lg:` not `md:` on the parent, and `min-w-0` on both halves, are
                both load-bearing. A <select>'s automatic minimum width is its
                longest option, so flex-shrink cannot bring a 256px control
                inside a 768px tablet row however much `min-w-0` is added, and
                the label block's own automatic minimum is its longest word. The
                app root clips the excess with `overflow-x-hidden`, so the
                control was 11px outside the viewport and unreachable. Stacking
                below `lg` also reads better on a tablet. */}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                    <h3 className="font-bold text-white tracking-wide">{title}</h3>
                    {action}
                </div>
                <p className="text-sm font-medium text-gray-400 mt-1">{description}</p>
            </div>
            <div className="lg:shrink-0 min-w-0 max-w-full w-full lg:w-auto lg:max-w-md">
                {children}
            </div>
        </div>
    );
}

// AI Settings Component
function AISettings({ settings, onUpdate, onSync, onReset }) {
    const { providers = [] } = useProvidersPageData();
    const setDefaultMutation = useSetLLMDefault();
    const llmStatus = useLLMProviderStatus();
    const routing = useLLMRouting();
    const catalog = useLLMCatalog();
    const { data: runtimeDefaults } = useLLMRuntimeDefaults();
    const [aiSyncState, setAiSyncState] = useState('idle');

    const llmProviders = providers.filter(p => p.worker_type === 'llm' || p.worker_type === 'hybrid' || (Array.isArray(p.capabilities) && p.capabilities.includes('llm')) || p.id.startsWith('llm'));

    const [providerId, setProviderId] = useState('');
    const [modelId, setModelId] = useState('');

    useEffect(() => {
        if (llmStatus.defaultProvider) {
            setProviderId(llmStatus.defaultProvider.provider_id || '');
            setModelId(llmStatus.defaultProvider.model_id || '');
        }
    }, [llmStatus.defaultProvider]);

    const handleSaveProvider = async () => {
        try {
            await setDefaultMutation.mutateAsync({ provider_id: providerId, model_id: modelId });
            toast.success('Default LLM provider updated');
        } catch (err) {
            toast.error(err?.message ? `Failed to update LLM provider: ${err.message}` : 'Failed to update LLM provider');
        }
    };

    // Seed local sliders from backend config (config.json ai block) so the
    // UI reflects the values actually used by chat/story generation.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await settingsApi.get();
                const ai = res?.settings?.ai;
                if (ai && !cancelled) {
                    const patch = {};
                    if (ai.maxContextTokens) patch.maxContextTokens = Number(ai.maxContextTokens);
                    if (ai.temperature != null) patch.temperature = Number(ai.temperature);
                    if (ai.top_p != null) patch.topP = Number(ai.top_p);
                    if (ai.max_output_tokens != null) patch.maxOutputTokens = Number(ai.max_output_tokens);
                    if (ai.frequency_penalty != null) patch.frequencyPenalty = Number(ai.frequency_penalty);
                    if (ai.presence_penalty != null) patch.presencePenalty = Number(ai.presence_penalty);
                    if (ai.ragEnabled != null) patch.ragEnabled = !!ai.ragEnabled;
                    if (ai.memoryExtractionEnabled != null) patch.memoryExtractionEnabled = !!ai.memoryExtractionEnabled;
                    if (ai.idleSimEnabled != null) patch.idleSimEnabled = !!ai.idleSimEnabled;
                    if (ai.idleSimIntervalSeconds != null) patch.idleSimIntervalSeconds = Number(ai.idleSimIntervalSeconds);
                    if (Object.keys(patch).length > 0) onSync(patch);
                }
            } catch {
                // Backend unreachable — keep local defaults.
            }
        })();
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleSaveAiBackend = async () => {
        setAiSyncState('saving');
        try {
            await settingsApi.update({
                ai: {
                    maxContextTokens: Number(settings.maxContextTokens),
                    temperature: Number(settings.temperature),
                    top_p: settings.topP == null ? null : Number(settings.topP),
                    max_output_tokens: settings.maxOutputTokens == null ? null : Number(settings.maxOutputTokens),
                    frequency_penalty: settings.frequencyPenalty == null ? null : Number(settings.frequencyPenalty),
                    presence_penalty: settings.presencePenalty == null ? null : Number(settings.presencePenalty),
                    ttsEnabled: settings.ttsEnabled,
                    ragEnabled: settings.ragEnabled !== false,
                    memoryExtractionEnabled: settings.memoryExtractionEnabled !== false,
                    idleSimEnabled: !!settings.idleSimEnabled,
                    idleSimIntervalSeconds: Number(settings.idleSimIntervalSeconds) || 600,
                }
            });
            toast.success('AI settings saved to backend');
            setAiSyncState('saved');
        } catch (err) {
            toast.error(err?.message ? `Failed to save AI settings: ${err.message}` : 'Failed to save AI settings');
            setAiSyncState('idle');
        }
    };

    const activeRp = catalog.data?.active?.rp || routing.data?.roles?.rp?.primary || 'Auto-detect';
    const activeUtil = catalog.data?.active?.util || routing.data?.roles?.util?.primary || 'Auto-detect';
    const activeDecisions = catalog.data?.active?.decisions || routing.data?.roles?.decisions?.primary || 'laya_multilingual';

    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <div>
                    <h2 className="text-2xl font-bold tracking-wide text-white">AI / LLM Settings</h2>
                    <p className="text-sm text-gray-400 mt-1">Quick inference defaults and links to the comprehensive LLM Studio.</p>
                </div>
                <div className="flex items-center gap-3">
                    <button onClick={handleSaveAiBackend} disabled={aiSyncState === 'saving'} className="px-4 py-2.5 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/30 rounded-xl text-blue-300 hover:text-blue-200 font-bold tracking-wide flex items-center gap-2 transition-all duration-300 disabled:opacity-50">
                        {aiSyncState === 'saving' ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        {aiSyncState === 'saved' ? 'Saved' : 'Save'}
                    </button>
                    <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                        <RotateCcw size={16} /> Reset
                    </button>
                </div>
            </div>

            {/* Consolidated LLM Studio Banner */}
            <div className="relative overflow-hidden rounded-2xl border border-blue-500/30 bg-gradient-to-r from-blue-950/40 via-purple-950/30 to-indigo-950/40 p-6 shadow-xl">
                <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div className="max-w-2xl">
                        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/20 border border-blue-500/30 text-blue-300 text-xs font-bold uppercase tracking-wider mb-3">
                            <Sparkles size={12} className="text-blue-400" />
                            Dedicated Workspace Available
                        </div>
                        <h3 className="text-xl font-bold text-white tracking-wide">Unified LLM & Agent Studio</h3>
                        <p className="text-sm text-gray-300 mt-1.5 leading-relaxed">
                            Model cluster routing, 16 System 1 Director decision gates, multi-agent pipelines (Character, Narrator, Updater, Illustrator), custom agent authoring, and the live pipeline simulator have been consolidated into the dedicated LLM Studio.
                        </p>
                    </div>
                    <div className="flex shrink-0">
                        <Link
                            to="/llm-studio"
                            className="px-5 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-sm tracking-wide flex items-center gap-2 shadow-lg shadow-blue-600/30 transition-all hover:scale-[1.02]"
                        >
                            <Brain size={18} />
                            Open LLM Studio
                            <ArrowRight size={16} />
                        </Link>
                    </div>
                </div>

                {/* Quick Studio Navigation Tiles */}
                <div className="relative z-10 mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3 pt-6 border-t border-white/10">
                    <Link
                        to="/llm-studio?tab=workflow"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-blue-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-blue-400 mb-1">
                                <GitBranch size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-blue-300">Pipeline Workflow</span>
                            </div>
                            <p className="text-2xs text-gray-400">Canonical 6-stage architecture & limits</p>
                        </div>
                        <div className="mt-2 text-2xs text-blue-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            View Flow <ArrowRight size={10} />
                        </div>
                    </Link>

                    <Link
                        to="/llm-studio?tab=agents"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-indigo-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-indigo-400 mb-1">
                                <Bot size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-indigo-300">Agent Studio</span>
                            </div>
                            <p className="text-2xs text-gray-400">Prompts, sub-variants & selection tags</p>
                        </div>
                        <div className="mt-2 text-2xs text-indigo-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            Configure <ArrowRight size={10} />
                        </div>
                    </Link>

                    <Link
                        to="/llm-studio?tab=questions"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-purple-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-purple-400 mb-1">
                                <HelpCircle size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-purple-300">Laya Questions</span>
                            </div>
                            <p className="text-2xs text-gray-400">Stage rubrics, toggles & custom questions</p>
                        </div>
                        <div className="mt-2 text-2xs text-purple-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            Edit Rubrics <ArrowRight size={10} />
                        </div>
                    </Link>

                    <Link
                        to="/llm-studio?tab=gates"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-emerald-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-emerald-400 mb-1">
                                <Shield size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-emerald-300">16-Gate Studio</span>
                            </div>
                            <p className="text-2xs text-gray-400">Director questions, weights & decision gates</p>
                        </div>
                        <div className="mt-2 text-2xs text-emerald-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            Tune Gates <ArrowRight size={10} />
                        </div>
                    </Link>

                    <Link
                        to="/llm-studio?tab=traces"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-cyan-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-cyan-400 mb-1">
                                <Activity size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-cyan-300">Decision Traces</span>
                            </div>
                            <p className="text-2xs text-gray-400">Turn telemetry, Fate checks & gate logs</p>
                        </div>
                        <div className="mt-2 text-2xs text-cyan-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            Inspect <ArrowRight size={10} />
                        </div>
                    </Link>

                    <Link
                        to="/llm-studio?tab=cluster"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-pink-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-pink-400 mb-1">
                                <Cpu size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-pink-300">Model Cluster</span>
                            </div>
                            <p className="text-2xs text-gray-400">RP, Util & Decisions models & fallbacks</p>
                        </div>
                        <div className="mt-2 text-2xs text-pink-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            Manage Models <ArrowRight size={10} />
                        </div>
                    </Link>

                    <Link
                        to="/llm-studio?tab=runtime"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-amber-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-amber-400 mb-1">
                                <Sliders size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-amber-300">Inference & Runtime</span>
                            </div>
                            <p className="text-2xs text-gray-400">Tokens, penalties, RAG, memory extraction</p>
                        </div>
                        <div className="mt-2 text-2xs text-amber-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            Edit Runtime <ArrowRight size={10} />
                        </div>
                    </Link>

                    <Link
                        to="/llm-studio?tab=simulator"
                        className="group p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-violet-500/40 transition-all text-left flex flex-col justify-between"
                    >
                        <div>
                            <div className="flex items-center gap-2 text-violet-400 mb-1">
                                <Play size={16} />
                                <span className="text-xs font-bold text-white group-hover:text-violet-300">Simulator</span>
                            </div>
                            <p className="text-2xs text-gray-400">Pipeline testbench & Director evaluation</p>
                        </div>
                        <div className="mt-2 text-2xs text-violet-400 font-semibold flex items-center gap-1 group-hover:translate-x-0.5 transition-transform">
                            Simulate <ArrowRight size={10} />
                        </div>
                    </Link>
                </div>
            </div>

            <div className="grid gap-6">
                {/* Live Worker & Active Cluster Summary */}
                <div className="p-6 border border-white/5 rounded-2xl bg-white/5 shadow-inner">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <h3 className="font-bold text-white tracking-wide flex items-center gap-2">
                                <Brain size={16} className="text-purple-400" />
                                Live LLM Cluster Status
                            </h3>
                            <p className="text-sm font-medium text-gray-400 mt-1">Overview of connected workers and active model dispatch roles.</p>
                        </div>
                        {llmStatus.isLoading ? (
                            <Loader2 size={18} className="animate-spin text-blue-400" />
                        ) : llmStatus.isHealthy ? (
                            <div className="flex items-center gap-2 text-green-400 text-sm font-bold">
                                <CheckCircle size={16} />
                                Connected
                            </div>
                        ) : (
                            <div className="flex items-center gap-2 text-red-400 text-sm font-bold">
                                <XCircle size={16} />
                                Unavailable
                            </div>
                        )}
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3 pt-2">
                        <div className="p-3.5 rounded-xl bg-gray-900/60 border border-white/5">
                            <span className="text-2xs font-bold uppercase tracking-widest text-blue-400 block mb-1">Roleplay (rp)</span>
                            <span className="text-xs font-semibold text-white font-mono block truncate" title={activeRp}>{activeRp}</span>
                            <span className="text-2xs text-gray-500 mt-1 block">Character dialogues & story prose</span>
                        </div>
                        <div className="p-3.5 rounded-xl bg-gray-900/60 border border-white/5">
                            <span className="text-2xs font-bold uppercase tracking-widest text-purple-400 block mb-1">Structured / Updater (util)</span>
                            <span className="text-xs font-semibold text-white font-mono block truncate" title={activeUtil}>{activeUtil}</span>
                            <span className="text-2xs text-gray-500 mt-1 block">Statekeeper updates & extraction</span>
                        </div>
                        <div className="p-3.5 rounded-xl bg-gray-900/60 border border-white/5">
                            <span className="text-2xs font-bold uppercase tracking-widest text-emerald-400 block mb-1">Decision Maker (decisions)</span>
                            <span className="text-xs font-semibold text-white font-mono block truncate" title={activeDecisions}>{activeDecisions}</span>
                            <span className="text-2xs text-emerald-400/80 mt-1 block">🧠 System 1 CPU/RAM (0 MB VRAM)</span>
                        </div>
                    </div>

                    <div className="mt-4 pt-3 border-t border-white/5 flex flex-wrap items-center justify-between gap-3 text-xs">
                        <div className="flex items-center gap-2 text-gray-400">
                            <span>Default Provider:</span>
                            <span className="font-semibold text-purple-300 font-mono">{llmStatus.defaultProvider?.provider_id || 'Auto-detect'}</span>
                            {llmStatus.enabledProviders.length > 0 && (
                                <span className="text-gray-500">({llmStatus.enabledProviders.length} enabled)</span>
                            )}
                        </div>
                        <Link
                            to="/llm-studio?tab=cluster"
                            className="text-blue-400 hover:text-blue-300 font-bold flex items-center gap-1"
                        >
                            Configure Model Routing & Fallbacks in LLM Studio <ArrowRight size={12} />
                        </Link>
                    </div>
                </div>

                <div className="p-6 border border-white/5 rounded-2xl bg-white/5 shadow-inner">
                    <div className="flex justify-between items-center mb-4">
                        <div>
                            <h3 className="font-bold text-white tracking-wide">Default LLM Provider</h3>
                            <p className="text-sm font-medium text-gray-400 mt-1">Configure the default backend provider for chat and generation.</p>
                        </div>
                        <button onClick={handleSaveProvider} disabled={setDefaultMutation.isPending} className="px-4 py-2 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/30 rounded-xl text-blue-300 hover:text-blue-200 font-bold tracking-wide flex items-center gap-2 transition-all duration-300 disabled:opacity-50">
                            {setDefaultMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                            Save
                        </button>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                        <div>
                            <label htmlFor="llm-default-provider" className="block text-sm font-bold uppercase tracking-widest text-gray-400 mb-2">Provider</label>
                            <select
                                id="llm-default-provider"
                                value={providerId}
                                onChange={(e) => setProviderId(e.target.value)}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-500"
                            >
                                <option value="">Auto-detect</option>
                                {llmProviders.map(p => (
                                    <option key={p.id} value={p.id}>{p.id}</option>
                                ))}
                            </select>
                        </div>
                        <div>
                            <label htmlFor="llm-default-model" className="block text-sm font-bold uppercase tracking-widest text-gray-400 mb-2">
                                Model ID (Optional)
                                {llmStatus.isModelsLoading && <Loader2 size={10} className="inline ml-1 animate-spin" />}
                            </label>
                            <select
                                id="llm-default-model"
                                value={modelId}
                                onChange={(e) => setModelId(e.target.value)}
                                className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-500"
                                disabled={llmStatus.isModelsLoading}
                            >
                                <option value="">Default Model</option>
                                {llmStatus.availableModels && llmStatus.availableModels.map(m => (
                                    <option key={m.id || m} value={m.id || m}>{m.name || m.id || m}</option>
                                ))}
                            </select>
                        </div>
                    </div>
                </div>

                {/* Quick Controls: Context Tokens, Temperature, TTS, RAG */}
                <SettingGroup title="Max Context Tokens" description="Maximum tokens to keep in chat history">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Maximum context tokens"
                            min="1024"
                            max="32768"
                            step="1024"
                            value={settings.maxContextTokens}
                            onChange={(e) => onUpdate('maxContextTokens', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm min-w-24 text-center bg-white/5 py-1.5 px-2 rounded-lg border border-white/5">
                            {settings.maxContextTokens ? `${settings.maxContextTokens.toLocaleString()} tok` : `Default (${(runtimeDefaults?.context_tokens ?? 4096).toLocaleString()})`}
                        </span>
                    </div>
                </SettingGroup>

                <SettingGroup title="Temperature" description="Controls randomness (0.0 = deterministic, 2.0 = highly random)">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            aria-label="Temperature"
                            min="0"
                            max="2"
                            step="0.1"
                            value={settings.temperature}
                            onChange={(e) => onUpdate('temperature', parseFloat(e.target.value))}
                            className="w-full md:w-64 accent-purple-500"
                        />
                        <span className="text-white font-bold text-sm w-16 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.temperature.toFixed(1)}</span>
                    </div>
                </SettingGroup>

                <SettingGroup
                    title="TTS (Text-to-Speech)"
                    description="Enable text-to-speech narration for chat messages"
                    action={
                        <button
                            onClick={() => onUpdate('ttsEnabled', !settings.ttsEnabled)}
                            className={`px-3 py-1 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                                settings.ttsEnabled
                                    ? 'bg-green-500/20 border border-green-500/30 text-green-400'
                                    : 'bg-gray-500/20 border border-gray-600/30 text-gray-500'
                            }`}
                        >
                            {settings.ttsEnabled ? 'On' : 'Off'}
                        </button>
                    }
                >
                    <p className="text-xs text-gray-500">
                        {settings.ttsEnabled
                            ? 'TTS narration is enabled. Messages will show a Play button to generate speech.'
                            : 'TTS narration is disabled. Enable to unlock voice generation for character messages.'}
                    </p>
                </SettingGroup>

                <SettingGroup
                    title="Autobiographical Memory (RAG)"
                    description="Semantic retrieval of character memories and lorebook entries in chat context"
                    action={
                        <button
                            onClick={() => onUpdate('ragEnabled', settings.ragEnabled === false)}
                            className={`px-3 py-1 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                                settings.ragEnabled !== false
                                    ? 'bg-green-500/20 border border-green-500/30 text-green-400'
                                    : 'bg-gray-500/20 border border-gray-600/30 text-gray-500'
                            }`}
                        >
                            {settings.ragEnabled !== false ? 'On' : 'Off'}
                        </button>
                    }
                >
                    <p className="text-xs text-gray-500">
                        {settings.ragEnabled !== false
                            ? 'RAG is enabled. Distant memories and lore entries are retrieved semantically into context.'
                            : 'RAG is disabled. No memories or lore entries are retrieved at all — there is no recency fallback, so the character relies only on the chat history already in context.'}
                    </p>
                    {settings.ragEnabled !== false && (
                        <div className="mt-4 pt-3 border-t border-white/5 space-y-1.5">
                            <div className="flex items-center justify-between">
                                <span className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Semantic Distance Cutoff</span>
                                <span className="text-xs font-mono text-purple-300 font-bold">{settings.ragMaxDistance ?? 0.6}</span>
                            </div>
                            <input
                                type="range"
                                min="0"
                                max="2"
                                step="0.05"
                                value={settings.ragMaxDistance ?? 0.6}
                                onChange={(e) => onUpdate('ragMaxDistance', parseFloat(e.target.value))}
                                className="w-full accent-blue-500"
                            />
                            <div className="flex justify-between text-2xs text-gray-500">
                                <span>0.0 (Strict / Identical)</span>
                                <span>0.6 (Recommended)</span>
                                <span>1.0 (Orthogonal)</span>
                                <span>2.0 (Unconditional Top-N)</span>
                            </div>
                            <p className="text-2xs text-gray-500 mt-1">
                                Cosine distance threshold: entries farther than this value are discarded from context injection to avoid noise.
                            </p>
                        </div>
                    )}
                </SettingGroup>

                {/* Collapsible System Prompts Section */}
                <details className="p-6 border border-white/5 rounded-2xl bg-white/5 shadow-inner group">
                    <summary className="cursor-pointer flex items-center justify-between list-none">
                        <div>
                            <h3 className="font-bold text-white tracking-wide flex items-center gap-2">
                                <Sparkles size={16} className="text-blue-400" />
                                System Prompt Blocks
                            </h3>
                            <p className="text-sm font-medium text-gray-400 mt-1">
                                Core system prompt blocks and generator templates. Also fully configurable with multi-agent tools in <Link to="/llm-studio?tab=runtime" className="text-blue-400 hover:underline">LLM Studio</Link>.
                            </p>
                        </div>
                        <div className="text-xs font-bold uppercase tracking-wider text-blue-400 px-3 py-1 rounded-lg bg-blue-500/10 border border-blue-500/20 group-open:bg-white/10 group-open:text-gray-300">
                            Toggle Editor
                        </div>
                    </summary>
                    <div className="mt-6 pt-4 border-t border-white/5">
                        <SystemPromptsEditor />
                    </div>
                </details>
            </div>
        </div>
    );
}

