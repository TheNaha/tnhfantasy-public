import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { createPortal } from 'react-dom';
import { AlertCircle, CheckCircle2, Loader2, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { providersApi } from '../../api';

const INPUT_CLASS = 'w-full rounded-lg border border-gray-700 bg-gray-800/80 px-4 py-3 text-white outline-none transition-colors focus:border-blue-500';
const LLM_PROVIDER_TYPES = new Set(['ollama', 'openai_compat', 'anthropic', 'google', 'modal_llm', 'modal_vllm']);

function defaultDeployConfig(type) {
    if (type === 'beam') {
        return {
            deploy_mode: 'managed',
            gpu_url: '',
            storage_url: '',
            download_url: '',
            gpu_type: 'RTX4090',
        };
    }
    
    if (type === 'ollama' || type === 'openai_compat' || type === 'anthropic' || type === 'google' || type === 'modal_llm' || type === 'modal_vllm') {
        return {
            deploy_mode: 'manual',
        };
    }

    if (type === 'direct_url' || type === 'remote_comfy') {
        return {
            deploy_mode: 'manual',
        };
    }

    if (type === 'modal_tts') {
        return {
            deploy_mode: 'manual',
            app_name: 'comfy-modal-tts',
        };
    }

    return {
        deploy_mode: 'managed',
        app_name: 'comfy-modal-stack',
        enable_memory_snapshot: false,
    };
}

function defaultRuntimeConfig() {
    return {
        mode: 'container',
        port: 8000,
    };
}

function sanitizeCredentials(credentials, preserveEmpty = false) {
    return Object.fromEntries(
        Object.entries(credentials || {}).filter(([, value]) => (
            preserveEmpty ? value !== undefined : value !== undefined && value !== ''
        ))
    );
}

export default function ProviderModal({ provider, onClose, onSave, saveProvider }) {
    // Escape dismisses, matching the shared ModalOverlay dialogs and the
    // "Esc → Close modals" line in KeyboardShortcutsModal.
    useEscapeKey(onClose);
    const initialType = provider?.type || 'modal';
    const [engineSchemas, setEngineSchemas] = useState(null);
    const [formData, setFormData] = useState({
        id: provider?.id || '',
        type: initialType,
        enabled: provider?.enabled ?? true,
        priority: provider?.priority ?? 1,
        runtime_config: provider?.runtime_config || defaultRuntimeConfig(),
        deploy_config: provider?.deploy_config || defaultDeployConfig(initialType),
        credentials: {},
    });
    // New providers default to the in-process engine path with no container
    // baggage (`runtime_config: null`): the backend resolves `in_process`
    // whenever the engine is constructible. The legacy container runtime is
    // opt-in per provider, and existing rows keep whatever they already have.
    const [enableRuntime, setEnableRuntime] = useState(Boolean(provider?.runtime_config));
    const [testingConnection, setTestingConnection] = useState(false);
    const [testResult, setTestResult] = useState(null);

    useEffect(() => {
        let mounted = true;
        providersApi.getSchemas()
            .then((data) => {
                if (mounted && data?.engines) {
                    setEngineSchemas(data.engines);
                }
            })
            .catch(() => {});
        return () => { mounted = false; };
    }, []);

    const currentSchema = engineSchemas?.[formData.type];

    const handleTestConnection = async () => {
        setTestingConnection(true);
        setTestResult(null);
        try {
            const rawCreds = sanitizeCredentials(formData.credentials);
            const payload = {
                id: formData.id ? formData.id.trim() : 'test-provider',
                type: formData.type,
                credentials: rawCreds,
                config: {
                    ...(formData.deploy_config || {}),
                },
            };
            if (rawCreds.base_url) payload.config.base_url = rawCreds.base_url;
            // Legacy key from older wizard versions: same canonical home.
            if (rawCreds.endpoint_url) payload.config.base_url = rawCreds.endpoint_url;
            if (rawCreds.comfy_url) payload.config.comfy_url = rawCreds.comfy_url;
            if (rawCreds.remote_agent_url) payload.config.remote_agent_url = rawCreds.remote_agent_url;

            const res = await providersApi.testConnection(payload);
            setTestResult(res);
            if (res.healthy) {
                toast.success(`Connected (${res.latency_ms || 0}ms)`);
            } else {
                toast.error(res.error || 'Connection failed');
            }
        } catch (err) {
            setTestResult({ healthy: false, error: err.message });
            toast.error(`Test failed: ${err.message}`);
        } finally {
            setTestingConnection(false);
        }
    };

    const credentialSummary = provider?.credential_summary || {};
    const configuredFields = credentialSummary.configured_fields || [];
    const accountLabel = credentialSummary.account_label || null;

    const credentialFields = useMemo(() => {
        if (currentSchema?.credentials) {
            return currentSchema.credentials;
        }

        // Pre-schema fallbacks (shown only while /schemas is loading, or for an
        // unknown type). Keys mirror the canonical registry field names so a
        // save from this path validates and resolves exactly like the
        // schema-driven form — no legacy `endpoint_url` credential key.
        if (formData.type === 'ollama') {
            return [
                { key: 'base_url', label: 'API Endpoint URL', type: 'text', placeholder: 'http://localhost:11434/v1' },
                { key: 'api_key', label: 'API Key (Optional)', type: 'password', placeholder: 'sk-...' },
            ];
        }

        if (formData.type === 'openai_compat') {
            return [
                { key: 'base_url', label: 'API Base URL', type: 'text', placeholder: 'https://api.openai.com/v1' },
                { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'sk-...' },
            ];
        }

        if (formData.type === 'anthropic') {
            return [
                { key: 'api_key', label: 'Anthropic API Key', type: 'password', placeholder: 'sk-ant-...' },
            ];
        }

        if (formData.type === 'google') {
            return [
                { key: 'api_key', label: 'Google AI API Key', type: 'password', placeholder: 'AIza...' },
            ];
        }

        if (formData.type === 'beam') {
            return [
                { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'beam_...' },
                { key: 'workspace_id', label: 'Workspace ID', type: 'text', placeholder: 'workspace-id' },
                { key: 'hf_token', label: 'HuggingFace Token', type: 'password', placeholder: 'hf_...' },
                { key: 'civitai_token', label: 'CivitAI Token', type: 'password', placeholder: 'CivitAI token' },
            ];
        }

        if (formData.type === 'direct_url') {
            return [
                { key: 'comfy_url', label: 'ComfyUI URL', type: 'text', placeholder: 'http://localhost:8188' },
                { key: 'comfyui_api_key', label: 'ComfyUI API Key (Optional)', type: 'password', placeholder: 'API key' },
            ];
        }

        if (formData.type === 'remote_comfy') {
            return [
                { key: 'remote_agent_url', label: 'Remote Agent URL', type: 'text', placeholder: 'http://remote-agent:8001' },
                { key: 'remote_agent_token', label: 'Remote Agent Token', type: 'password', placeholder: 'Agent token' },
                { key: 'comfyui_api_key', label: 'ComfyUI API Key (Optional)', type: 'password', placeholder: 'API key' },
                { key: 'hf_token', label: 'HuggingFace Token', type: 'password', placeholder: 'hf_...' },
                { key: 'civitai_token', label: 'CivitAI Token', type: 'password', placeholder: 'CivitAI token' },
            ];
        }

        if (formData.type === 'modal_tts') {
            return [
                { key: 'token_id', label: 'Modal Token ID', type: 'password', placeholder: 'ak-...' },
                { key: 'token_secret', label: 'Modal Token Secret', type: 'password', placeholder: 'as-...' },
            ];
        }

        return [
            { key: 'token_id', label: 'Token ID', type: 'text', placeholder: 'ak-...' },
            { key: 'token_secret', label: 'Token Secret', type: 'password', placeholder: 'as-...' },
            { key: 'username', label: 'Username', type: 'text', placeholder: 'modal-username' },
            { key: 'hf_token', label: 'HuggingFace Token', type: 'password', placeholder: 'hf_...' },
            { key: 'civitai_token', label: 'CivitAI Token', type: 'password', placeholder: 'CivitAI token' },
        ];
    }, [formData.type, currentSchema]);

    const handleTypeChange = (type) => {
        setFormData((current) => ({
            ...current,
            type,
            deploy_config: provider?.type === type
                ? (provider.deploy_config || defaultDeployConfig(type))
                : defaultDeployConfig(type),
            credentials: {},
        }));
    };

    const updateRuntimeConfig = (updates) => {
        setFormData((current) => ({
            ...current,
            runtime_config: {
                ...(current.runtime_config || defaultRuntimeConfig()),
                ...updates,
            },
        }));
    };

    const updateDeployConfig = (updates) => {
        setFormData((current) => ({
            ...current,
            deploy_config: {
                ...(current.deploy_config || defaultDeployConfig(current.type)),
                ...updates,
            },
        }));
    };

    const handleSubmit = async (event) => {
        event.preventDefault();

        const effectiveWorkerType = formData.type === 'modal_tts' ? 'tts' : (LLM_PROVIDER_TYPES.has(formData.type) ? 'llm' : 'image');
        const payload = {
            id: formData.id.trim(),
            type: formData.type,
            worker_type: effectiveWorkerType,
            declared_capabilities: [effectiveWorkerType],
            enabled: formData.enabled,
            priority: Number(formData.priority) || 1,
            config: {
                ...(formData.deploy_config || {}),
                ...(formData.type === 'modal' || formData.type === 'modal_tts'
                    ? { app_name: formData.deploy_config?.app_name || (formData.type === 'modal_tts' ? 'comfy-modal-tts' : 'comfy-modal-stack') }
                    : {}),
            },
            runtime_config: enableRuntime
                ? {
                    ...(formData.runtime_config || defaultRuntimeConfig()),
                    port: Number(formData.runtime_config?.port || 8000),
                }
                : null,
            deploy_config: {
                ...(formData.deploy_config || defaultDeployConfig(formData.type)),
                deploy_mode: formData.deploy_config?.deploy_mode || 'managed',
            },
        };

        const credentials = sanitizeCredentials(formData.credentials);
        // URL-ish entries typed into the credentials section belong to the
        // canonical config keys (the registry schemas render them there).
        // `endpoint_url` is the pre-overhaul legacy key — still honoured.
        const urlMoves = [];
        if (credentials.base_url || credentials.endpoint_url) {
            payload.config.base_url = credentials.base_url || credentials.endpoint_url;
            urlMoves.push('base_url', 'endpoint_url');
        }
        if (credentials.comfy_url || credentials.remote_agent_url) {
            if (credentials.comfy_url) payload.config.comfy_url = credentials.comfy_url;
            if (credentials.remote_agent_url) payload.config.remote_agent_url = credentials.remote_agent_url;
            urlMoves.push('comfy_url', 'remote_agent_url');
        }
        for (const key of urlMoves) delete credentials[key];
        if (!provider || Object.keys(credentials).length > 0) {
            payload.credentials = credentials;
        }

        try {
            await saveProvider(provider, payload);
            toast.success(provider ? 'Provider updated' : 'Provider created');
            await onSave();
        } catch (error) {
            toast.error(error.message || 'Failed to save provider');
        }
    };

    return createPortal(
        <motion.div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
        >
            <motion.div
                className="w-full max-w-3xl max-h-[92vh] overflow-y-auto rounded-2xl border border-white/10 bg-gray-900 p-8 shadow-2xl"
                initial={{ scale: 0.96, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.96, opacity: 0 }}
                onClick={(event) => event.stopPropagation()}
            >
                <h2 className="mb-2 text-2xl font-semibold text-white">
                    {provider ? 'Edit Provider' : 'Add Provider'}
                </h2>
                <p className="mb-6 text-sm text-gray-400">
                    Providers now use a unified runtime, deploy, and credential model.
                </p>

                <form onSubmit={handleSubmit} className="space-y-4 md:space-y-6">
                    <Section title="Basics">
                        <div className="grid gap-4 md:grid-cols-2">
                            <Field label="Provider ID">
                                <input
                                    type="text"
                                    value={formData.id}
                                    onChange={(event) => setFormData((current) => ({ ...current, id: event.target.value }))}
                                    disabled={Boolean(provider)}
                                    required
                                    className={INPUT_CLASS}
                                    placeholder="modal-primary"
                                />
                            </Field>

                            <Field label="Type">
                                <select
                                    value={formData.type}
                                    onChange={(event) => handleTypeChange(event.target.value)}
                                    className={INPUT_CLASS}
                                >
                                    <optgroup label="Image Workers">
                                        <option value="modal">Modal (ComfyUI)</option>
                                        <option value="beam">Beam.cloud (ComfyUI)</option>
                                        <option value="direct_url">Direct URL (ComfyUI)</option>
                                        <option value="remote_comfy">Remote ComfyUI Agent</option>
                                    </optgroup>
                                    <optgroup label="LLM Workers">
                                        <option value="openai_compat">OpenAI / OpenAI-Compatible API</option>
                                        <option value="ollama">Local LLM Worker (Ollama / LM Studio)</option>
                                        <option value="anthropic">Anthropic (Claude)</option>
                                        <option value="google">Google AI (Gemini)</option>
                                        <option value="modal_vllm">Modal vLLM (High-Throughput)</option>
                                        <option value="modal_llm">Modal LLM</option>
                                    </optgroup>
                                    <optgroup label="Voice & Audio (TTS)">
                                        <option value="modal_tts">Modal Kokoro / TTS</option>
                                    </optgroup>
                                </select>
                                {currentSchema?.description && (
                                    <p className="mt-2 text-xs text-blue-300/80 bg-blue-950/40 border border-blue-800/30 rounded-lg p-2.5">
                                        {currentSchema.description}
                                    </p>
                                )}
                            </Field>

                            <Field label="Priority">
                                <input
                                    type="number"
                                    min="1"
                                    value={formData.priority}
                                    onChange={(event) => setFormData((current) => ({ ...current, priority: event.target.value }))}
                                    className={INPUT_CLASS}
                                />
                            </Field>

                            <Field label="Enabled">
                                <label className="inline-flex h-12 items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/60 px-4 text-sm text-gray-200">
                                    <input
                                        type="checkbox"
                                        checked={formData.enabled}
                                        onChange={(event) => setFormData((current) => ({ ...current, enabled: event.target.checked }))}
                                    />
                                    Route jobs to this provider
                                </label>
                            </Field>
                        </div>
                    </Section>

                    <Section title="Account Credentials">
                        {provider && (
                            <div className="mb-4 rounded-xl border border-blue-500/25 bg-blue-500/10 p-4 text-sm text-blue-100">
                                <div className="font-medium text-blue-200">
                                    Existing credentials are redacted
                                </div>
                                {accountLabel && <div className="mt-1 text-blue-200/80">Account: {accountLabel}</div>}
                                {configuredFields.length > 0 && (
                                    <div className="mt-1 text-blue-200/80">
                                        Configured: {configuredFields.join(', ')}
                                    </div>
                                )}
                                <div className="mt-2 text-blue-200/70">
                                    Leave fields blank to keep current secrets unchanged.
                                </div>
                            </div>
                        )}

                        <div className="grid gap-4 md:grid-cols-2">
                            {credentialFields.map((field) => (
                                <Field key={field.key} label={field.label}>
                                    <input
                                        type={field.type}
                                        value={formData.credentials[field.key] || ''}
                                        onChange={(event) => setFormData((current) => ({
                                            ...current,
                                            credentials: {
                                                ...current.credentials,
                                                [field.key]: event.target.value,
                                            },
                                        }))}
                                        className={INPUT_CLASS}
                                        placeholder={field.placeholder}
                                    />
                                </Field>
                            ))}
                        </div>
                    </Section>

                    <Section title="Engine & Execution Mode">
                        <div className="space-y-3">
                            <div className="rounded-xl border border-blue-500/25 bg-blue-500/10 p-3.5 text-xs text-blue-200">
                                <span className="font-semibold text-blue-300">In-Process Engine Active:</span> This provider executes directly within the backend without separate Docker container overhead, port bindings, or socket proxying.
                            </div>
                            <details className="text-xs text-gray-400 group">
                                <summary className="cursor-pointer hover:text-gray-300 select-none py-1">
                                    Advanced / Legacy Container Settings
                                </summary>
                                <div className="mt-3 space-y-3 pl-2 border-l border-gray-800">
                                    <label className="inline-flex items-center gap-2 text-gray-300">
                                        <input
                                            type="checkbox"
                                            checked={enableRuntime}
                                            onChange={(event) => setEnableRuntime(event.target.checked)}
                                        />
                                        Enable legacy container runtime (Deprecated)
                                    </label>
                                    {enableRuntime && (
                                        <div className="grid gap-4 md:grid-cols-2 pt-2">
                                            <Field label="Runtime Port">
                                                <input
                                                    type="number"
                                                    min="1"
                                                    value={formData.runtime_config?.port || 8000}
                                                    onChange={(event) => updateRuntimeConfig({ port: Number(event.target.value) })}
                                                    className={INPUT_CLASS}
                                                />
                                            </Field>
                                            <Field label="Container Name">
                                                <input
                                                    type="text"
                                                    value={formData.runtime_config?.container_name || ''}
                                                    onChange={(event) => updateRuntimeConfig({ container_name: event.target.value })}
                                                    className={INPUT_CLASS}
                                                    placeholder={`tnhcomfy-${formData.id || formData.type}`}
                                                />
                                            </Field>
                                        </div>
                                    )}
                                </div>
                            </details>
                        </div>
                    </Section>

                    <Section title="Engine Configuration">
                        <div className="grid gap-4 md:grid-cols-2">
                            <Field label="Deploy Mode">
                                <select
                                    value={formData.deploy_config?.deploy_mode || 'managed'}
                                    onChange={(event) => updateDeployConfig({ deploy_mode: event.target.value })}
                                    className={INPUT_CLASS}
                                >
                                    <option value="managed">Managed</option>
                                    <option value="manual">Manual</option>
                                </select>
                            </Field>

                            {currentSchema?.config ? (
                                currentSchema.config.map((field) => {
                                    const val = formData.deploy_config?.[field.key] ?? field.default ?? '';
                                    if (field.type === 'checkbox') {
                                        return (
                                            <Field key={field.key} label={field.label}>
                                                <label className="inline-flex h-12 items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/60 px-4 text-sm text-gray-200 cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        checked={Boolean(val)}
                                                        onChange={(event) => updateDeployConfig({ [field.key]: event.target.checked })}
                                                        className="rounded border-gray-700 bg-gray-900 text-blue-600 focus:ring-blue-500"
                                                    />
                                                    <span>{field.help_text || field.label}</span>
                                                </label>
                                            </Field>
                                        );
                                    }
                                    if (field.type === 'select') {
                                        return (
                                            <Field key={field.key} label={field.label}>
                                                <select
                                                    value={val}
                                                    onChange={(event) => updateDeployConfig({ [field.key]: event.target.value })}
                                                    className={INPUT_CLASS}
                                                >
                                                    {(field.options || []).map((opt) => (
                                                        <option key={opt} value={opt}>{opt}</option>
                                                    ))}
                                                </select>
                                            </Field>
                                        );
                                    }
                                    if (field.type === 'number') {
                                        return (
                                            <Field key={field.key} label={field.label}>
                                                <input
                                                    type="number"
                                                    min={field.min}
                                                    max={field.max}
                                                    step={field.step || 1}
                                                    value={val}
                                                    onChange={(event) => updateDeployConfig({ [field.key]: Number(event.target.value) })}
                                                    className={INPUT_CLASS}
                                                    placeholder={field.placeholder || ''}
                                                />
                                            </Field>
                                        );
                                    }
                                    return (
                                        <Field key={field.key} label={field.label}>
                                            <input
                                                type="text"
                                                value={val}
                                                onChange={(event) => updateDeployConfig({ [field.key]: event.target.value })}
                                                className={INPUT_CLASS}
                                                placeholder={field.placeholder || ''}
                                            />
                                        </Field>
                                    );
                                })
                            ) : (
                                <>
                                    {formData.type === 'modal' || formData.type === 'modal_tts' ? (
                                        <Field label="App Name">
                                            <input
                                                type="text"
                                                value={formData.deploy_config?.app_name || ''}
                                                onChange={(event) => updateDeployConfig({ app_name: event.target.value })}
                                                className={INPUT_CLASS}
                                                placeholder={formData.type === 'modal_tts' ? 'comfy-modal-tts' : 'comfy-modal-stack'}
                                            />
                                        </Field>
                                    ) : formData.type === 'beam' ? (
                                        <Field label="GPU Type">
                                            <input
                                                type="text"
                                                value={formData.deploy_config?.gpu_type || ''}
                                                onChange={(event) => updateDeployConfig({ gpu_type: event.target.value })}
                                                className={INPUT_CLASS}
                                                placeholder="RTX4090"
                                            />
                                        </Field>
                                    ) : null}
                                </>
                            )}
                        </div>

                        {formData.deploy_config?.deploy_mode === 'manual' && (
                            <div className="mt-4 rounded-xl border border-yellow-500/25 bg-yellow-500/10 p-4 text-sm text-yellow-100">
                                Manual deploy mode disables the in-app deploy action. The provider can still run workloads if the runtime is reachable.
                            </div>
                        )}
                    </Section>

                    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-800 pt-4">
                        <div className="flex items-center gap-2">
                            <button
                                type="button"
                                onClick={handleTestConnection}
                                disabled={testingConnection}
                                className="inline-flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-800/80 px-3.5 py-2 text-xs font-medium text-gray-200 transition-colors hover:bg-gray-700 disabled:opacity-50"
                            >
                                {testingConnection ? (
                                    <>
                                        <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />
                                        Testing...
                                    </>
                                ) : (
                                    <>
                                        <RefreshCw className="h-3.5 w-3.5 text-gray-400" />
                                        Test Connection
                                    </>
                                )}
                            </button>
                            {testResult && (
                                <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${testResult.healthy ? 'text-green-400' : 'text-red-400'}`}>
                                    {testResult.healthy ? (
                                        <>
                                            <CheckCircle2 className="h-3.5 w-3.5" />
                                            Connected {testResult.latency_ms ? `(${testResult.latency_ms}ms)` : ''}
                                        </>
                                    ) : (
                                        <>
                                            <AlertCircle className="h-3.5 w-3.5" />
                                            {testResult.error || 'Failed'}
                                        </>
                                    )}
                                </span>
                            )}
                        </div>
                        <div className="flex items-center gap-3">
                            <button
                                type="button"
                                onClick={onClose}
                                className="rounded-lg border border-gray-700 bg-gray-800 px-4 py-2 text-sm text-gray-200 transition-colors hover:bg-gray-700"
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
                            >
                                {provider ? 'Save Changes' : 'Create Provider'}
                            </button>
                        </div>
                    </div>
                </form>
            </motion.div>
        </motion.div>,
        document.body
    );
}

function Section({ title, children }) {
    return (
        <section className="rounded-2xl border border-gray-800 bg-gray-950/60 p-5">
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wide text-gray-400">{title}</h3>
            {children}
        </section>
    );
}

function Field({ label, children }) {
    return (
        <label className="block space-y-2">
            <span className="text-sm font-medium text-gray-300">{label}</span>
            {children}
        </label>
    );
}
