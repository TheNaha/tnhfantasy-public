import { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { createPortal } from 'react-dom';
import toast from 'react-hot-toast';

const INPUT_CLASS = 'w-full rounded-lg border border-gray-700 bg-gray-800/80 px-4 py-3 text-white outline-none transition-colors focus:border-blue-500';

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
    
    if (type === 'llm-local') {
        return {
            deploy_mode: 'manual',
        };
    }

    if (type === 'llm-openai-compat') {
        return {
            deploy_mode: 'manual',
        };
    }

    if (type === 'llm-anthropic') {
        return {
            deploy_mode: 'manual',
        };
    }

    if (type === 'llm-google') {
        return {
            deploy_mode: 'manual',
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
        port: 8001,
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
    const initialType = provider?.type || 'modal';
    const [formData, setFormData] = useState({
        id: provider?.id || '',
        type: initialType,
        enabled: provider?.enabled ?? true,
        priority: provider?.priority ?? 1,
        runtime_config: provider?.runtime_config || defaultRuntimeConfig(),
        deploy_config: provider?.deploy_config || defaultDeployConfig(initialType),
        credentials: {},
    });
    const [enableRuntime, setEnableRuntime] = useState(Boolean(provider?.runtime_config || !provider));

    const credentialSummary = provider?.credential_summary || {};
    const configuredFields = credentialSummary.configured_fields || [];
    const accountLabel = credentialSummary.account_label || null;

    const credentialFields = useMemo(() => {
        if (formData.type === 'llm-local') {
            return [
                { key: 'endpoint_url', label: 'API Endpoint URL', type: 'text', placeholder: 'http://localhost:11434' },
                { key: 'api_key', label: 'API Key (Optional)', type: 'password', placeholder: 'sk-...' },
            ];
        }

        if (formData.type === 'llm-openai-compat') {
            return [
                { key: 'endpoint_url', label: 'API Base URL', type: 'text', placeholder: 'https://api.openai.com/v1' },
                { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'sk-...' },
            ];
        }

        if (formData.type === 'llm-anthropic') {
            return [
                { key: 'api_key', label: 'Anthropic API Key', type: 'password', placeholder: 'sk-ant-...' },
            ];
        }

        if (formData.type === 'llm-google') {
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

        if (formData.type === 'kaggle') {
            return [
                { key: 'username', label: 'Kaggle Username', type: 'text', placeholder: 'kaggle-username' },
                { key: 'api_key', label: 'Kaggle API Key', type: 'password', placeholder: 'kaggle-key' },
                { key: 'hf_token', label: 'HuggingFace Token', type: 'password', placeholder: 'hf_...' },
                { key: 'civitai_token', label: 'CivitAI Token', type: 'password', placeholder: 'CivitAI token' },
            ];
        }

        return [
            { key: 'token_id', label: 'Token ID', type: 'text', placeholder: 'ak-...' },
            { key: 'token_secret', label: 'Token Secret', type: 'password', placeholder: 'as-...' },
            { key: 'username', label: 'Username', type: 'text', placeholder: 'modal-username' },
            { key: 'hf_token', label: 'HuggingFace Token', type: 'password', placeholder: 'hf_...' },
            { key: 'civitai_token', label: 'CivitAI Token', type: 'password', placeholder: 'CivitAI token' },
        ];
    }, [formData.type]);

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

        const payload = {
            id: formData.id.trim(),
            type: formData.type,
            worker_type: formData.type.startsWith('llm') ? 'llm' : 'image',
            enabled: formData.enabled,
            priority: Number(formData.priority) || 1,
            runtime_config: enableRuntime
                ? {
                    ...(formData.runtime_config || defaultRuntimeConfig()),
                    port: Number(formData.runtime_config?.port || 8001),
                }
                : null,
            deploy_config: {
                ...(formData.deploy_config || defaultDeployConfig(formData.type)),
                deploy_mode: formData.deploy_config?.deploy_mode || 'managed',
            },
        };

        const credentials = sanitizeCredentials(formData.credentials);
        if (!provider || Object.keys(credentials).length > 0) {
            payload.credentials = credentials;
        }

        try {
            await saveProvider(provider, payload);
            toast.success(provider ? 'Provider updated' : 'Provider created');
            await onSave();
        } catch (error) {
            console.error('Failed to save provider:', error);
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
                                        <option value="kaggle">Kaggle (ComfyUI)</option>
                                    </optgroup>
                                    <optgroup label="LLM Workers">
                                        <option value="llm-local">Local LLM Worker (Ollama / LM Studio)</option>
                                        <option value="llm-openai-compat">OpenAI / OpenAI-Compatible API</option>
                                        <option value="llm-anthropic">Anthropic (Claude)</option>
                                        <option value="llm-google">Google AI (Gemini)</option>
                                    </optgroup>
                                </select>
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

                    <Section title="Runtime Settings">
                        <div className="space-y-4">
                            <label className="inline-flex items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/60 px-4 py-3 text-sm text-gray-200">
                                <input
                                    type="checkbox"
                                    checked={enableRuntime}
                                    onChange={(event) => setEnableRuntime(event.target.checked)}
                                />
                                Enable dedicated runtime container for this provider
                            </label>

                            {enableRuntime ? (
                                <div className="grid gap-4 md:grid-cols-2">
                                    <Field label="Runtime Port">
                                        <input
                                            type="number"
                                            min="1"
                                            value={formData.runtime_config?.port || 8001}
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
                                            placeholder={`comfy-provider-${formData.id || formData.type}`}
                                        />
                                    </Field>
                                </div>
                            ) : (
                                <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-200">
                                    This provider will not manage a local runtime container. Use this for manual/external runtimes only.
                                </div>
                            )}
                        </div>
                    </Section>

                    <Section title="Deployment Settings">
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

                            {formData.type === 'modal' ? (
                                <Field label="App Name">
                                    <input
                                        type="text"
                                        value={formData.deploy_config?.app_name || ''}
                                        onChange={(event) => updateDeployConfig({ app_name: event.target.value })}
                                        className={INPUT_CLASS}
                                        placeholder="comfy-modal-stack"
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

                            {formData.type === 'modal' ? (
                                <Field label="Memory Snapshot">
                                    <label className="inline-flex h-12 items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/60 px-4 text-sm text-gray-200">
                                        <input
                                            type="checkbox"
                                            checked={Boolean(formData.deploy_config?.enable_memory_snapshot)}
                                            onChange={(event) => updateDeployConfig({ enable_memory_snapshot: event.target.checked })}
                                        />
                                        Enable experimental fast cold starts
                                    </label>
                                </Field>
                            ) : formData.type === 'beam' ? (
                                <>
                                    <Field label="GPU Endpoint URL">
                                        <input
                                            type="text"
                                            value={formData.deploy_config?.gpu_url || ''}
                                            onChange={(event) => updateDeployConfig({ gpu_url: event.target.value })}
                                            className={INPUT_CLASS}
                                            placeholder="https://beam.example/gpu"
                                        />
                                    </Field>
                                    <Field label="Storage Endpoint URL">
                                        <input
                                            type="text"
                                            value={formData.deploy_config?.storage_url || ''}
                                            onChange={(event) => updateDeployConfig({ storage_url: event.target.value })}
                                            className={INPUT_CLASS}
                                            placeholder="https://beam.example/storage"
                                        />
                                    </Field>
                                    <Field label="Download Endpoint URL">
                                        <input
                                            type="text"
                                            value={formData.deploy_config?.download_url || ''}
                                            onChange={(event) => updateDeployConfig({ download_url: event.target.value })}
                                            className={INPUT_CLASS}
                                            placeholder="https://beam.example/download"
                                        />
                                    </Field>
                                </>
                            ) : null}
                        </div>

                        {formData.deploy_config?.deploy_mode === 'manual' && (
                            <div className="rounded-xl border border-yellow-500/25 bg-yellow-500/10 p-4 text-sm text-yellow-100">
                                Manual deploy mode disables the in-app deploy action. The provider can still run workloads if the runtime is reachable.
                            </div>
                        )}
                    </Section>

                    <div className="flex items-center justify-end gap-3 border-t border-gray-800 pt-4">
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
