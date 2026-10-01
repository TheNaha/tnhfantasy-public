import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Settings as SettingsIcon, RotateCcw, Save, Info, Server, Brain, Loader2, CheckCircle, XCircle, Volume2 } from 'lucide-react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { settingsApi } from '../api/settingsApi';
import { useConfirmation } from '../store/confirmationStore';
import { useSettings, useUpdateSettings } from '../store/settingsStore';
import { useBranding, useSaveBranding } from '../hooks/useBranding';
import { useLLMProviderStatus, useSetLLMDefault } from '../hooks/useLLMProviderStatus';
import useProvidersPageData from '../hooks/useProvidersPageData';
import React, { useCallback, useEffect, useRef } from 'react';


function SystemPromptsEditor() {
    const queryClient = useQueryClient();
    const { data: blocksData, isLoading } = useQuery({
        queryKey: ['system_prompts_blocks'],
        queryFn: () => settingsApi.getSystemPrompts(),
        staleTime: 30000,
    });
    const [draft, setDraft] = useState({});
    const [saving, setSaving] = useState(false);
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
            toast.success('System prompts updated');
            queryClient.invalidateQueries({ queryKey: ['system_prompts_blocks'] });
        } catch {
            toast.error('Failed to save system prompts');
        } finally {
            setSaving(false);
        }
    };

    const fields = [
        { key: 'roleplay_default', label: 'Roleplay Default', desc: 'Default instructions used in every chat reply (before character prompt). Clear to disable.' },
        { key: 'narrator', label: 'Narrator Prompt', desc: 'Prompt used for narration scenes (narrate_scene tool and /narrate mode).' },
        { key: 'suggest_instruction', label: 'Suggest Instruction', desc: 'Instructions appended when suggesting user replies (/suggest).' },
    ];

    if (isLoading) return <div className="text-xs text-gray-500">Loading prompts…</div>;

    return (
        <SettingGroup title="System Prompt Blocks" description="These blocks make up the assembled prompt. The Roleplay Default applies to all chat replies. Edit and save to update config.json directly.">
            <div className="space-y-4">
                {fields.map(f => (
                    <div key={f.key}>
                        <label className="block text-xs font-bold uppercase tracking-widest text-gray-500 mb-1">{f.label}</label>
                        <p className="text-xs text-gray-600 mb-1">{f.desc}</p>
                        <textarea
                            value={draft[f.key] || ''}
                            onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                            rows={4}
                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-300 focus:outline-none focus:border-blue-500 resize-y min-h-[60px] font-sans"
                        />
                    </div>
                ))}
            </div>
            <div className="mt-3 flex justify-end">
                <button
                    onClick={handleSave}
                    disabled={saving || isLoading}
                    className="btn-primary px-4 py-2 text-xs flex items-center gap-2"
                >
                    {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                    Save prompts
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

    // `generator.default_checkpoint` lives on the server; the local store key is
    // only a mirror (ChatWorkspaceContext sends it per message). Keeping the
    // mirror in step here means any path that writes the category — including
    // the Generator tab's Reset — cannot leave it stale.
    const handleMirroredDefaultCheckpoint = useCallback((value) => {
        if (updateSetting) updateSetting('generator', 'defaultCheckpoint', value);
    }, [updateSetting]);

    const handleUpdateSetting = (category, key, value) => {
        updateSetting(category, key, value);
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

    const handleTestToast = (type) => {
        const duration = type === 'success' ? settings.ui.toastSuccessDuration : settings.ui.toastErrorDuration;
        if (type === 'success') {
            toast.success(`Test toast (${duration}ms duration)`, { duration });
        } else {
            toast.error(`Test error toast (${duration}ms duration)`, { duration });
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
                                onTestToast={handleTestToast}
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
                                onMirrorDefaultCheckpoint={handleMirroredDefaultCheckpoint}
                            />
                        )}

                        {activeTab === 'backend' && (
                            <BackendSettings onMirroredDefaultCheckpoint={handleMirroredDefaultCheckpoint} />
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

function BackendSettings({ onMirroredDefaultCheckpoint }) {
    const queryClient = useQueryClient();
    const { data: configResponse, isLoading } = useSettingsConfig();
    const { data: schemaResponse } = useSettingsSchema();
    const [draft, setDraft] = useState(null);
    const [saving, setSaving] = useState(false);
    const [saveState, setSaveState] = useState('idle');

    // Seed the draft from the server config, and mirror the fallback checkpoint
    // into the local store so ChatWorkspaceContext can keep sending it per
    // message as `generator_checkpoint`.
    useEffect(() => {
        const settings = configResponse?.settings;
        if (!settings) return;
        setDraft(settings);
        if (onMirroredDefaultCheckpoint) {
            onMirroredDefaultCheckpoint(settings.generator?.default_checkpoint || null);
        }
    }, [configResponse, onMirroredDefaultCheckpoint]);

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
function UISettings({ settings, onUpdate, onReset, onTestToast }) {
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
                        value={settings.defaultViewMode}
                        onChange={(e) => onUpdate('defaultViewMode', e.target.value)}
                        aria-label="Default view mode"
                        className="w-full lg:w-64 max-w-full min-w-0 bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 text-white font-medium focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus outline-none"
                    >
                        <option value="grid">Grid</option>
                        <option value="list">List</option>
                        <option value="feed">Feed</option>
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
                    action={
                        <button
                            onClick={() => onTestToast('success')}
                            className="text-2xs font-bold uppercase tracking-widest px-4 py-1.5 bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 rounded-lg text-green-400 transition-colors shadow-inner"
                        >
                            Test
                        </button>
                    }
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
                    action={
                        <button
                            onClick={() => onTestToast('error')}
                            className="text-2xs font-bold uppercase tracking-widest px-4 py-1.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 transition-colors shadow-inner"
                        >
                            Test
                        </button>
                    }
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

                <SettingGroup title="Auto-Remove Downloads" description="Automatically remove download status after completion">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.autoRemoveDownloads}
                                onChange={(e) => onUpdate('autoRemoveDownloads', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.autoRemoveDownloads ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>
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
        if (onMirror) onMirror(serverValue || null);
    }, [serverValue, onMirror]);

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
        <>
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
                <p className="mt-2 text-xs text-amber-300">
                    The configured checkpoint is not among the installed models, so generations fall back to it and will fail
                    until it is installed or a different one is selected.
                </p>
            )}
        </>
    );
}

// Generator Settings Component
function GeneratorSettings({ settings, onUpdate, onReset, onMirrorDefaultCheckpoint }) {
    const { modelsByKey, loading } = useModelDirectories([{ directory: 'models/checkpoints', key: 'checkpoints' }]);
    const checkpoints = modelsByKey.checkpoints || [];
    const { data: configResponse } = useSettingsConfig();

    const handleReset = () => {
        onReset();
        // The checkpoint is server-owned, so restoring the local category
        // defaults must not blank its mirror in the store.
        if (onMirrorDefaultCheckpoint) {
            onMirrorDefaultCheckpoint(configResponse?.settings?.generator?.default_checkpoint || null);
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
            <div className="lg:shrink-0 min-w-0 max-w-full w-full lg:w-auto">
                {children}
            </div>
        </div>
    );
}

// AI Settings Component
function AISettings({ settings, onUpdate, onSync, onReset }) {
    const { providers = [] } = useProvidersPageData();
    const llmStatus = useLLMProviderStatus();
    const setDefaultMutation = useSetLLMDefault();
    
    const llmProviders = providers.filter(p => p.worker_type === 'llm' || p.id.startsWith('llm'));

    const [providerId, setProviderId] = useState('');
    const [modelId, setModelId] = useState('');

    useEffect(() => {
        if (llmStatus.defaultProvider) {
            // syncing form state from fetched provider config (external system)
            setProviderId(llmStatus.defaultProvider.provider_id || '');
            setModelId(llmStatus.defaultProvider.model_id || '');
        }
    }, [llmStatus.defaultProvider]);

    const handleSaveProvider = async () => {
        try {
            await setDefaultMutation.mutateAsync({ provider_id: providerId, model_id: modelId });
            toast.success('Default LLM provider updated');
        } catch {
            toast.error('Failed to update LLM provider');
        }
    };

    const [aiSyncState, setAiSyncState] = useState('idle');

    // Seed local sliders from backend config (config.json `ai` block) so the
    // UI reflects the values actually used by chat/story generation.
    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await settingsApi.get();
                const ai = res?.settings?.ai;
                if (ai && !cancelled) {
                    // One set() for the whole patch: eight updateSetting calls
                    // re-rendered every useSettings() consumer eight times and
                    // fired eight "Setting updated!" toasts on mount.
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
        } catch {
            toast.error('Failed to save AI settings');
            setAiSyncState('idle');
        }
    };

    return (
        <div className="space-y-4 md:space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">AI / LLM Settings</h2>
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

            <div className="grid gap-6">
                {/* LLM Worker Status Indicator */}
                <div className="p-6 border border-white/5 rounded-2xl bg-white/5 shadow-inner">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <h3 className="font-bold text-white tracking-wide flex items-center gap-2">
                                <Brain size={16} className="text-purple-400" />
                                LLM Worker Status
                            </h3>
                            <p className="text-sm font-medium text-gray-400 mt-1">Live connection status and available models from LLM providers.</p>
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

                    {llmStatus.enabledProviders.length === 0 ? (
                        <div className="text-sm text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-4 py-3">
                            No LLM providers configured. Add one in the <strong>Providers</strong> page to enable chat and story generation.
                        </div>
                    ) : (
                        <div className="grid gap-2">
                            <div className="text-xs font-bold uppercase tracking-widest text-gray-500">
                                Enabled Providers ({llmStatus.enabledProviders.length})
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {llmStatus.enabledProviders.map(p => (
                                    <span key={p.provider_id} className="px-2.5 py-1 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-bold flex items-center gap-1.5">
                                        <Server size={10} />
                                        {p.provider_id}
                                        {p.is_default && <span className="text-2xs bg-purple-400/20 px-1 py-0.5 rounded">DEFAULT</span>}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                <div className="p-6 border border-white/5 rounded-2xl bg-white/5 shadow-inner">
                    <div className="flex justify-between items-center mb-4">
                        <div>
                            <h3 className="font-bold text-white tracking-wide">Default LLM Provider</h3>
                            <p className="text-sm font-medium text-gray-400 mt-1">Configure the default backend provider for chat and generation.</p>
                        </div>
                        <button onClick={handleSaveProvider} disabled={setDefaultMutation.isPending} className="btn-primary px-4 py-2 flex items-center gap-2">
                            {setDefaultMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                            Save
                        </button>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                        <div>
                            <label className="block text-sm font-bold uppercase tracking-widest text-gray-400 mb-2">Provider</label>
                            <select
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
                            <label className="block text-sm font-bold uppercase tracking-widest text-gray-400 mb-2">
                                Model ID (Optional)
                                {llmStatus.isModelsLoading && <Loader2 size={10} className="inline ml-1 animate-spin" />}
                            </label>
                            <select
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
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.maxContextTokens}</span>
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
                    title="Sampling Defaults"
                    description="Global LLM sampling defaults. Per-chat and per-story overrides take precedence; blank = provider default. Penalties are ignored by engines that don't support them."
                >
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        {[
                            { key: 'topP', label: 'Top P', min: 0, max: 1, step: 0.01 },
                            { key: 'maxOutputTokens', label: 'Max Output Tokens', min: 16, max: 32768, step: 16 },
                            { key: 'frequencyPenalty', label: 'Frequency Penalty', min: -2, max: 2, step: 0.1 },
                            { key: 'presencePenalty', label: 'Presence Penalty', min: -2, max: 2, step: 0.1 },
                        ].map(({ key, label, min, max, step }) => (
                            <label key={key} className="flex flex-col gap-1.5">
                                <span className="text-xs uppercase tracking-wider text-gray-500 font-bold">{label}</span>
                                <div className="flex items-center gap-1">
                                    <input
                                        type="number"
                                        min={min}
                                        max={max}
                                        step={step}
                                        placeholder="default"
                                        value={settings[key] ?? ''}
                                        onChange={(e) => onUpdate(key, e.target.value === '' ? null : Number(e.target.value))}
                                        className="w-full bg-white/5 py-1.5 px-2 rounded-lg border border-white/10 text-white text-sm focus:outline-none focus:border-blue-500/50 placeholder-gray-600"
                                    />
                                    {settings[key] != null && (
                                        <button
                                            onClick={() => onUpdate(key, null)}
                                            className="p-1 text-gray-500 hover:text-red-400 transition-colors"
                                            title="Reset to engine default"
                                        >
                                            <RotateCcw size={12} />
                                        </button>
                                    )}
                                </div>
                            </label>
                        ))}
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
                </SettingGroup>

                <SettingGroup
                    title="Memory Extraction"
                    description="Background LLM calls that turn finished conversations into durable character memories"
                    action={
                        <button
                            onClick={() => onUpdate('memoryExtractionEnabled', settings.memoryExtractionEnabled === false)}
                            className={`px-3 py-1 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                                settings.memoryExtractionEnabled !== false
                                    ? 'bg-green-500/20 border border-green-500/30 text-green-400'
                                    : 'bg-gray-500/20 border border-gray-600/30 text-gray-500'
                            }`}
                        >
                            {settings.memoryExtractionEnabled !== false ? 'On' : 'Off'}
                        </button>
                    }
                >
                    <p className="text-xs text-gray-500">
                        {settings.memoryExtractionEnabled !== false
                            ? 'Extraction is enabled. Every few user turns a background LLM call reads the recent conversation and writes durable memories. This is a real billable call, and it also runs for swipes, regenerations and idle-simulation replies. Memories are de-duplicated before writing, so repeats do not accumulate.'
                            : 'Extraction is off. No background LLM calls are made, so memory extraction costs nothing — but the character stops learning new durable facts from conversations. Existing memories are kept and still retrieved.'}
                    </p>
                </SettingGroup>

                <SettingGroup
                    title="Idle Simulation"
                    description="Characters keep the scene alive with proactive in-character messages while you're away"
                    action={
                        <button
                            onClick={() => onUpdate('idleSimEnabled', !settings.idleSimEnabled)}
                            className={`px-3 py-1 rounded-lg text-xs font-bold uppercase tracking-wider transition-all ${
                                settings.idleSimEnabled
                                    ? 'bg-green-500/20 border border-green-500/30 text-green-400'
                                    : 'bg-gray-500/20 border border-gray-600/30 text-gray-500'
                            }`}
                        >
                            {settings.idleSimEnabled ? 'On' : 'Off'}
                        </button>
                    }
                >
                    <p className="text-xs text-gray-500">
                        {settings.idleSimEnabled
                            ? `Idle simulation is enabled. Dormant chats will receive periodic updates every ${Math.round((settings.idleSimIntervalSeconds || 600) / 60)} minutes.`
                            : 'Idle simulation is disabled. Enable to let characters act autonomously in dormant chats.'}
                    </p>
                    {settings.idleSimEnabled && (
                        <div className="mt-3 flex items-center gap-2">
                            <span className="text-xs text-gray-500 uppercase tracking-wider">Interval (min)</span>
                            <input
                                type="number"
                                min="5"
                                max="1440"
                                step="5"
                                value={Math.round((settings.idleSimIntervalSeconds || 600) / 60)}
                                onChange={(e) => onUpdate('idleSimIntervalSeconds', (parseInt(e.target.value) || 10) * 60)}
                                className="w-20 px-2 py-1 bg-gray-900 border border-gray-700 rounded text-white text-xs focus:outline-none focus:border-blue-500"
                            />
                        </div>
                    )}
                </SettingGroup>

                <SettingGroup title="CharGen: Description Prompt" description="System prompt for generating character description">
                    <textarea
                        value={settings.charGenDescriptionPrompt || ''}
                        onChange={(e) => onUpdate('charGenDescriptionPrompt', e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 min-h-[100px] resize-y"
                    />
                </SettingGroup>

                <SettingGroup title="CharGen: Personality Prompt" description="System prompt for generating character personality">
                    <textarea
                        value={settings.charGenPersonalityPrompt || ''}
                        onChange={(e) => onUpdate('charGenPersonalityPrompt', e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 min-h-[100px] resize-y"
                    />
                </SettingGroup>

                <SettingGroup title="CharGen: Scenario Prompt" description="System prompt for generating character scenario">
                    <textarea
                        value={settings.charGenScenarioPrompt || ''}
                        onChange={(e) => onUpdate('charGenScenarioPrompt', e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 min-h-[100px] resize-y"
                    />
                </SettingGroup>

                <SettingGroup title="CharGen: First Message Prompt" description="System prompt for generating character first message">
                    <textarea
                        value={settings.charGenFirstMesPrompt || ''}
                        onChange={(e) => onUpdate('charGenFirstMesPrompt', e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 min-h-[100px] resize-y"
                    />
                </SettingGroup>

                <SettingGroup title="CharGen: Message Examples Prompt" description="System prompt for generating character message examples">
                    <textarea
                        value={settings.charGenMesExamplePrompt || ''}
                        onChange={(e) => onUpdate('charGenMesExamplePrompt', e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 min-h-[100px] resize-y"
                    />
                </SettingGroup>

                <SettingGroup title="CharGen: System Prompt Prompt" description="System prompt for generating character system prompt">
                    <textarea
                        value={settings.charGenSystemPromptPrompt || ''}
                        onChange={(e) => onUpdate('charGenSystemPromptPrompt', e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 min-h-[100px] resize-y"
                    />
                </SettingGroup>

                <SettingGroup title="CharGen: Visual Tags Prompt" description="System prompt for generating character visual tags">
                    <textarea
                        value={settings.charGenVisualTagsPrompt || ''}
                        onChange={(e) => onUpdate('charGenVisualTagsPrompt', e.target.value)}
                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-4 py-3 text-white focus:outline-none focus:border-blue-500 min-h-[100px] resize-y"
                    />
                </SettingGroup>

                {/* System Prompt Blocks (config-driven) */}
                <SystemPromptsEditor />
            </div>
        </div>
    );
}
