import { useState } from 'react';
import {
    AlertCircle,
    Eye,
    EyeOff,
    Key,
    Plus,
    RefreshCw,
    Save,
    Shield,
    Trash2,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { providersApi } from '../../../api';
import { QueryErrorState } from '../../common/QueryState';
import { PROVIDERS_PAGE_QUERY_KEYS } from '../../../hooks/useProvidersPageData';

const INPUT_CLASS =
    'w-full rounded-lg border border-gray-700 bg-gray-800/80 px-4 py-2.5 text-sm text-white ' +
    'outline-none transition-colors placeholder-gray-500 focus:border-blue-500';

const COMMON_KEYS = ['token_id', 'token_secret', 'api_key'];

function formatMaskHint(hint) {
    if (!hint) return '••••••••';
    if (typeof hint === 'string') return hint;
    if (typeof hint === 'object') {
        return hint.masked || (hint.set ? '••••••••' : '');
    }
    return String(hint);
}

/** A password-type text input whose visibility can be toggled and whose
 *  value is never pre-filled from the server. */
function CredentialField({ name, value, onChange, onRemove }) {
    const [show, setShow] = useState(false);
    return (
        <div className="flex items-center gap-2">
            <div className="flex-1">
                <label className="mb-1 block text-xs font-medium text-gray-400 font-mono">
                    {name}
                </label>
                <div className="relative">
                    <input
                        type={show ? 'text' : 'password'}
                        value={value ?? ''}
                        onChange={(e) => onChange(e.target.value)}
                        placeholder={`Enter ${name}`}
                        className={INPUT_CLASS}
                    />
                    <button
                        type="button"
                        onClick={() => setShow(!show)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-400 hover:text-gray-200"
                        title={show ? 'Hide value' : 'Show value'}
                        aria-label={show ? `Hide ${name}` : `Show ${name}`}
                    >
                        {show ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                </div>
            </div>
            {onRemove && (
                <button
                    type="button"
                    onClick={onRemove}
                    className="mt-5 p-2 text-gray-500 hover:text-red-400 transition-colors"
                    title={`Discard ${name}`}
                    aria-label={`Discard ${name}`}
                >
                    <Trash2 size={16} />
                </button>
            )}
        </div>
    );
}

export default function CredentialsTab({ providerId, credentialSummary }) {
    const queryClient = useQueryClient();
    const [form, setForm] = useState({});
    const [customKey, setCustomKey] = useState('');
    const [setError, setSetError] = useState(null);

    const {
        data: credData,
        isLoading,
        isError,
        error,
        refetch,
    } = useQuery({
        queryKey: ['provider-credentials', providerId],
        queryFn: () => providersApi.getCredentials(providerId),
        staleTime: 30_000,
        enabled: !!providerId,
    });

    // Prefer the live API call; fall back to the summary injected by the parent.
    const masked = credData?.credentials ?? credentialSummary?.credentials ?? {};
    const encryption = credData?.encryption ?? credentialSummary?.encryption ?? {
        enabled: false,
    };

    const setValue = (name, value) =>
        setForm((prev) => ({ ...prev, [name]: value }));

    const removeField = (name) => {
        setForm((prev) => {
            const next = { ...prev };
            delete next[name];
            return next;
        });
    };

    const addKeyField = (keyToAdd) => {
        const trimmed = (keyToAdd || '').trim();
        if (!trimmed) return;
        setForm((prev) => ({ ...prev, [trimmed]: prev[trimmed] ?? '' }));
        setCustomKey('');
    };

    const setMutation = useMutation({
        mutationFn: (payload) =>
            providersApi.setCredentials(providerId, payload.credentials),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['provider-credentials', providerId] });
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
            setForm({});
            setSetError(null);
        },
        onError: (e) => setSetError(e?.message ?? 'Failed to save credentials'),
    });

    const deleteMutation = useMutation({
        mutationFn: ({ key }) => providersApi.deleteCredential(providerId, key),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['provider-credentials', providerId] });
            queryClient.invalidateQueries({ queryKey: PROVIDERS_PAGE_QUERY_KEYS.providers });
            setSetError(null);
        },
        onError: (e) => setSetError(e?.message ?? 'Failed to delete credential'),
    });

    if (isLoading && !credData) {
        return (
            <div className="flex items-center justify-center py-10 text-gray-400">
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                Loading credentials…
            </div>
        );
    }

    if (isError && !credData) {
        return (
            <div className="mb-4">
                <QueryErrorState error={error} noun="credentials" onRetry={() => refetch()} />
            </div>
        );
    }

    const formKeys = Object.keys(form);
    const existingKeys = Object.keys(masked);
    const hasUnsavedChanges = formKeys.some((k) => (form[k] ?? '').length > 0);

    return (
        <div className="space-y-5">
            {/* Encryption status banner */}
            <div
                className={`flex items-center gap-3 rounded-xl p-3.5 text-sm border ${
                    encryption.enabled
                        ? 'bg-emerald-950/30 border-emerald-800/40 text-emerald-300'
                        : 'bg-amber-950/30 border-amber-800/40 text-amber-300'
                }`}
            >
                {encryption.enabled ? (
                    <Shield className="h-5 w-5 flex-shrink-0 text-emerald-400" />
                ) : (
                    <AlertCircle className="h-5 w-5 flex-shrink-0 text-amber-400" />
                )}
                <span>
                    {encryption.enabled
                        ? 'Credentials are encrypted at rest with Fernet (COMFY_CREDENTIAL_SECRET).'
                        : 'Credentials stored in database without active encryption key.'}
                </span>
            </div>

            {/* Existing stored credentials (masked, deletion only) */}
            <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400">
                    Stored Credentials ({existingKeys.length})
                </h4>
                {existingKeys.length === 0 ? (
                    <p className="text-sm text-gray-500 italic">No credentials currently stored for this provider.</p>
                ) : (
                    <div className="flex flex-wrap gap-2">
                        {Object.entries(masked).map(([key, maskHint]) => (
                            <span
                                key={key}
                                className="inline-flex items-center gap-2 rounded-lg bg-gray-800/90 border border-gray-700/60 px-3 py-1.5 text-xs text-gray-300"
                            >
                                <Key className="h-3.5 w-3.5 text-blue-400" />
                                <span className="font-mono font-medium text-white">{key}</span>
                                <span className="text-gray-500 font-mono">
                                    {formatMaskHint(maskHint)}
                                </span>
                                <button
                                    type="button"
                                    onClick={() => deleteMutation.mutate({ key })}
                                    disabled={deleteMutation.isPending}
                                    className="ml-1 rounded p-1 text-gray-400 hover:text-red-400 transition-colors disabled:opacity-50"
                                    title={`Delete ${key}`}
                                    aria-label={`Delete ${key}`}
                                >
                                    <Trash2 className="h-3.5 w-3.5" />
                                </button>
                            </span>
                        ))}
                    </div>
                )}
            </div>

            {/* Set / update credentials form */}
            <div className="border-t border-gray-800/80 pt-4">
                <h4 className="mb-1 text-xs font-semibold uppercase tracking-wider text-gray-400">
                    Update Credentials
                </h4>
                <p className="mb-3 text-xs text-gray-500">
                    Enter new values to set or update. Values are write-only and cannot be read back.
                </p>

                {formKeys.length > 0 ? (
                    <div className="space-y-3 mb-4">
                        {formKeys.map((name) => (
                            <CredentialField
                                key={name}
                                name={name}
                                value={form[name]}
                                onChange={(v) => setValue(name, v)}
                                onRemove={() => removeField(name)}
                            />
                        ))}
                    </div>
                ) : null}

                {/* Quick add common keys & custom key input */}
                <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs text-gray-500">Quick add:</span>
                        {COMMON_KEYS.filter((k) => !formKeys.includes(k) && !existingKeys.includes(k)).map((k) => (
                            <button
                                key={k}
                                type="button"
                                onClick={() => addKeyField(k)}
                                className="inline-flex items-center gap-1 rounded-md bg-gray-800 px-2 py-1 text-xs font-mono text-gray-300 hover:bg-gray-700 hover:text-white transition-colors border border-gray-700"
                            >
                                <Plus size={12} /> {k}
                            </button>
                        ))}
                    </div>

                    <div className="flex gap-2">
                        <input
                            type="text"
                            placeholder="Custom key name (e.g. secret_token)"
                            value={customKey}
                            onChange={(e) => setCustomKey(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault();
                                    addKeyField(customKey);
                                }
                            }}
                            className="flex-1 rounded-lg border border-gray-700 bg-gray-800/80 px-3 py-2 text-xs font-mono text-gray-200 outline-none focus:border-blue-500 placeholder-gray-500"
                        />
                        <button
                            type="button"
                            onClick={() => addKeyField(customKey)}
                            disabled={!customKey.trim()}
                            className="inline-flex items-center gap-1 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-xs font-medium text-gray-200 hover:bg-gray-700 disabled:opacity-40 transition-colors"
                        >
                            <Plus size={14} /> Add Field
                        </button>
                    </div>
                </div>

                {setError && (
                    <p className="mt-3 text-xs text-red-400 bg-red-950/30 p-2.5 rounded-lg border border-red-800/40">
                        {setError}
                    </p>
                )}

                {formKeys.length > 0 && (
                    <div className="mt-4 flex items-center gap-3">
                        <button
                            type="button"
                            onClick={() => {
                                const toSave = Object.fromEntries(
                                    Object.entries(form).filter(([, v]) => (v ?? '').trim() !== '')
                                );
                                if (Object.keys(toSave).length === 0) return;
                                setSetError(null);
                                setMutation.mutate({ credentials: toSave });
                            }}
                            disabled={setMutation.isPending || !hasUnsavedChanges}
                            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 hover:bg-blue-500 px-4 py-2.5 text-xs font-medium text-white transition-colors disabled:opacity-50 shadow-md shadow-blue-600/20"
                        >
                            {setMutation.isPending ? (
                                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                                <Save className="h-3.5 w-3.5" />
                            )}
                            Save Credentials
                        </button>
                        <button
                            type="button"
                            onClick={() => setForm({})}
                            disabled={setMutation.isPending}
                            className="rounded-lg border border-gray-700 px-3 py-2 text-xs font-medium text-gray-400 hover:bg-gray-800 hover:text-gray-200 transition-colors"
                        >
                            Clear Form
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}
