import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { createPortal } from 'react-dom';
import { AlertCircle, CheckCircle2, Loader2, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { providersApi } from '../../api';

const INPUT_CLASS = 'w-full rounded-lg border border-gray-700 bg-gray-800/80 px-4 py-3 text-white outline-none transition-colors focus:border-blue-500';

// Static fallback type list: rendered only while GET /schemas is loading
// (or if it fails). The canonical source is the backend registry served by
// that endpoint — adding a provider type must never require editing this
// file again.
//
// Grouped by TRANSPORT (how the backend reaches the compute), not by category.
// Three categories x four transports is the matrix the registry declares, and
// grouping by transport is what makes it legible: pick "Beam.cloud (serverless)"
// and you see Image + LLM + TTS under it, which is exactly what the backend's
// PROVIDER_MATRIX says that transport offers. Grouping by category instead —
// which is what this file used to do — produced one flat "Language Models" list
// of seven options where three said "Direct" only in the label.
const FALLBACK_TRANSPORTS = [
    { id: 'modal', label: 'Modal (serverless)' },
    { id: 'beam', label: 'Beam.cloud (serverless)' },
    { id: 'remote', label: 'Self-hosted container' },
    { id: 'direct', label: 'Direct API endpoint' },
];

const CATEGORY_LABEL = {
    image: 'Image Generation',
    llm: 'Language Models',
    tts: 'Voice & Audio',
};

// Display names for the fallback path, keyed by provider type id.
const FALLBACK_TYPE_NAMES = {
    modal: 'Modal (ComfyUI)', modal_tts: 'Modal (TTS)', modal_vllm: 'Modal (LLM)',
    beam: 'Beam (ComfyUI)', beam_llm: 'Beam (LLM)', beam_tts: 'Beam (TTS)',
    remote_comfy: 'Container (ComfyUI + agent)', remote_llm: 'Self-hosted LLM container',
    remote_tts: 'Self-hosted TTS container',
    direct_url: 'Direct ComfyUI server', direct_tts: 'Direct ComfyUI (TTS)',
    openai_compat: 'Direct: OpenAI-compatible API', ollama: 'Direct: Ollama / LM Studio',
    anthropic: 'Direct: Anthropic Claude', google: 'Direct: Google Gemini',
};

// (transport, category) -> provider type id. Mirrors the backend's
// PROVIDER_MATRIX; the API's own `matrix` replaces this once loaded.
const FALLBACK_MATRIX = {
    modal:   { image: 'modal',          llm: null,                    tts: 'modal_tts' },
    beam:    { image: 'beam',           llm: 'beam_llm',              tts: 'beam_tts' },
    remote:  { image: 'remote_comfy',   llm: 'remote_llm',            tts: 'remote_tts' },
    direct:  { image: 'direct_url',     llm: null,                    tts: 'direct_tts' },
};

// Worker-type fallback for the save payload before schemas load.
const FALLBACK_WORKER_TYPE = {
    modal: 'image', beam: 'image', remote_comfy: 'image', direct_url: 'image',
    modal_vllm: 'llm', beam_llm: 'llm', remote_llm: 'llm',
    openai_compat: 'llm', ollama: 'llm', anthropic: 'llm', google: 'llm',
    modal_tts: 'tts', beam_tts: 'tts', remote_tts: 'tts', direct_tts: 'tts',
};

// Defaults contributed by a schema's config fields (checkboxes, selects,
// app names). Render and save both fall back to these so an untouched
// form still carries the registry defaults.
function schemaConfigDefaults(schema) {
    const out = {};
    for (const field of schema?.config || []) {
        if (field && field.key !== undefined && 'default' in field) out[field.key] = field.default;
    }
    return out;
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
    const [schemasPayload, setSchemasPayload] = useState(null);
    const engineSchemas = schemasPayload?.engines || null;
    const [formData, setFormData] = useState({
        id: provider?.id || '',
        type: initialType,
        enabled: provider?.enabled ?? true,
        priority: provider?.priority ?? 1,
        deploy_config: provider?.deploy_config || {},
        credentials: {},
    });
    // In-process engines are the only runtime: new providers carry no
    // runtime_config (the backend resolves `in_process` whenever the engine
    // is constructible). Existing rows keep whatever they already have —
    // the legacy container runtime has no UI anymore.
    const preservedRuntimeConfig = provider?.runtime_config ?? null;
    const [testingConnection, setTestingConnection] = useState(false);
    const [testResult, setTestResult] = useState(null);

    useEffect(() => {
        let mounted = true;
        providersApi.getSchemas()
            .then((data) => {
                // The WHOLE payload, not just `engines`: `transports` and
                // `matrix` are what let this modal render the category x
                // transport grid, and dropping them reduced the UI to the
                // flat per-category list the matrix was added to replace.
                if (mounted && data?.engines) setSchemasPayload(data);
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

    // Schema-only credential fields. There is intentionally no hardcoded
    // fallback list per type: the registry served by GET /schemas is the
    // single source of truth, and a duplicated list here would drift again
    // (the same class of bug the backend factory dedup just fixed).
    const credentialFields = useMemo(() => currentSchema?.credentials || [], [currentSchema]);
    const schemasLoaded = engineSchemas != null;

    // Type options grouped by TRANSPORT, with the category as each option's own
    // label. One `optgroup` per transport is what makes the 3x4 matrix legible:
    // a user choosing "Beam.cloud (serverless)" sees Image + LLM + TTS together,
    // which is what that transport is declared to offer.
    //
    // Every transport is listed even when a category cell is empty (Direct LLM
    // is a *family* of hosted APIs rather than one type), because an omitted
    // cell reads as "this transport cannot do LLMs" — which is false here and
    // was the original reason four cells went missing from the product.
    const typeOptions = useMemo(() => {
        const engines = engineSchemas || {};
        const transportList = schemasPayload?.transports || FALLBACK_TRANSPORTS;
        const matrix = schemasPayload?.matrix || null;

        // Before the payload arrives there is no `engines` map to iterate, so the
        // fallback grid has to be built from the static matrix. Returning an
        // empty list here would leave the select blank for the whole load —
        // which is exactly what a bare `return []` fallback used to do before
        // the type options were grouped at all.
        if (!schemasPayload?.engines) {
            return transportList.map((transport) => {
                const cells = matrix || FALLBACK_MATRIX[transport.id] || {};
                const options = Object.entries(cells)
                    .filter(([, id]) => id)
                    .map(([category, id]) => ({
                        value: id,
                        label: `${CATEGORY_LABEL[category] || category} — ${FALLBACK_TYPE_NAMES[id] || id}`,
                    }));
                // The static matrix is declared in category order already.
                return { group: transport.label, transport: transport.id, options };
            }).filter((g) => g.options.length > 0);
        }

        const transports = transportList;

        const groups = transports.map((transport) => {
            const transportId = transport.id || transport.value;
            const options = [];
            for (const [key, schema] of Object.entries(engines)) {
                // `id` is what the API sends; `value` is accepted too so a
                // hand-written payload works. Comparing against the wrong key
                // does not error — `schema.transport !== undefined` is simply
                // always true, so every option is filtered out and the select
                // renders empty, which reads as "no provider types exist".
                if (schema.transport !== transportId) continue;
                const category = schema.category || schema.worker_type || 'image';
                options.push({
                    value: key,
                    category,
                    label: `${CATEGORY_LABEL[category] || category} — ${schema.name || key}`,
                });
            }
            // The registry's own order is insertion order, not UI order. Sort
            // within a transport so the three categories always read Image, LLM,
            // TTS — keyed on the CATEGORY, not the option value: `order` is
            // keyed by category, so indexing it by a provider type id gave 0 for
            // every row and the sort was a silent no-op.
            const order = { image: 0, llm: 1, tts: 2 };
            // `??`, NOT `||`: `order['image']` is 0, and `0 || 9` is 9 — the
            // legitimate value for Image is falsy, so `||` ranks it LAST. No
            // error, just the three categories quietly reading LLM, TTS, Image.
            options.sort((a, b) => (order[a.category] ?? 99) - (order[b.category] ?? 99));
            return { group: transport.label, transport: transport.id, options, matrix };
        });

        return groups.filter((g) => g.options.length > 0 || g.matrix);
    }, [engineSchemas, schemasPayload]);

    const handleTypeChange = (type) => {
        setFormData((current) => ({
            ...current,
            type,
            deploy_config: provider?.type === type
                ? (provider.deploy_config || {})
                : schemaConfigDefaults(engineSchemas?.[type]),
            credentials: {},
        }));
    };

    const updateDeployConfig = (updates) => {
        setFormData((current) => ({
            ...current,
            deploy_config: {
                ...(current.deploy_config || {}),
                ...updates,
            },
        }));
    };

    const handleSubmit = async (event) => {
        event.preventDefault();

        const effectiveWorkerType = currentSchema?.worker_type
            || FALLBACK_WORKER_TYPE[formData.type]
            || 'image';
        const engineConfig = { ...(formData.deploy_config || {}) };
        // Container-era baggage is never written: the backend resolves
        // in-process engines from credentials + engine config alone.
        delete engineConfig.deploy_mode;
        const payload = {
            id: formData.id.trim(),
            type: formData.type,
            worker_type: effectiveWorkerType,
            declared_capabilities: [effectiveWorkerType],
            enabled: formData.enabled,
            priority: Number(formData.priority) || 1,
            config: {
                ...schemaConfigDefaults(currentSchema),
                ...engineConfig,
            },
            runtime_config: preservedRuntimeConfig,
            deploy_config: engineConfig,
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
                                    {typeOptions.map((group) => (
                                        <optgroup key={group.group} label={group.group}>
                                            {group.options.map((opt) => (
                                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                                            ))}
                                        </optgroup>
                                    ))}
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

                        {credentialFields.length > 0 ? (
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
                        ) : (
                            <p className="text-sm text-gray-400">
                                {schemasLoaded
                                    ? 'This provider type needs no credentials — everything is configured below.'
                                    : 'Loading engine schema…'}
                            </p>
                        )}
                    </Section>

                    <Section title="Engine Configuration">
                        {!schemasLoaded ? (
                            <p className="text-sm text-gray-400">Loading engine schema…</p>
                        ) : (currentSchema?.config?.length > 0 ? (
                        <div className="grid gap-4 md:grid-cols-2">
                            {currentSchema.config.map((field) => {
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
                                })}
                        </div>
                        ) : (
                            <p className="text-sm text-gray-400">
                                This provider type has no engine settings — credentials above are everything it needs.
                            </p>
                        ))}
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
