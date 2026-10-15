import { useState, useEffect, useRef } from 'react';
import {
    AlertCircle,
    CheckCircle2,
    Copy,
    Loader2,
    RefreshCw,
    Rocket,
    Terminal,
} from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { providersApi } from '../../../api';
import { copyToClipboard } from '../../../utils/clipboard';
import { formatTimestamp } from '../../../utils/dateTime';
import { getDeployTargetForProvider } from '../../../utils/providerStatus';
import { QueryErrorState } from '../../common/QueryState';

const TARGET_DETAILS = {
    image: {
        label: 'Modal ComfyUI (Image)',
        artifact: 'comfy-modal-stack',
        transport: 'Modal',
        description: 'Deployables under deployables/modal/image/ (ComfyUI serverless)',
    },
    tts: {
        label: 'Modal TTS Worker',
        artifact: 'comfy-modal-tts',
        transport: 'Modal',
        description: 'Deployables under deployables/modal/tts/ (TTS serverless)',
    },
    llm: {
        label: 'Modal LLM Worker',
        artifact: 'tnh-llm',
        transport: 'Modal',
        description: 'Deployables under deployables/modal/llm/ (llama.cpp serverless)',
    },
    beam: {
        label: 'Beam.cloud Workers',
        artifact: 'comfy-gpu + 5 more',
        transport: 'Beam',
        description: 'Deployables under deployables/beam/ (6 serverless deployments)',
    },
};

export default function DeployTab({ provider }) {
    const queryClient = useQueryClient();
    const consoleRef = useRef(null);
    const [dryRun, setDryRun] = useState(false);
    const [elapsedSeconds, setElapsedSeconds] = useState(0);
    const [copied, setCopied] = useState(false);

    // Live streaming states
    const [isDeploying, setIsDeploying] = useState(false);
    const [streamOutput, setStreamOutput] = useState('');
    const [streamResult, setStreamResult] = useState(null);
    const [streamError, setStreamError] = useState(null);

    const target = getDeployTargetForProvider(provider);
    const details = TARGET_DETAILS[target] || {
        label: `${provider?.type || 'Cloud'} Worker`,
        artifact: 'custom-artifact',
        transport: provider?.type || 'Cloud',
        description: 'Serverless cloud compute worker',
    };

    // Query persisted deployment logs & activity
    const {
        data: logsData,
        isLoading: logsLoading,
        isError: logsIsError,
        error: logsError,
        refetch: refetchLogs,
    } = useQuery({
        queryKey: ['provider-logs', provider?.id],
        queryFn: () => providersApi.getLogs(provider.id),
        enabled: Boolean(provider?.id),
        staleTime: 5000,
    });

    // Auto-scroll terminal console as output streams in
    useEffect(() => {
        if (consoleRef.current) {
            consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
        }
    }, [streamOutput]);

    // Live timer while deploying
    useEffect(() => {
        let timer = null;
        if (isDeploying) {
            timer = setInterval(() => {
                setElapsedSeconds((s) => s + 1);
            }, 1000);
        }
        return () => {
            if (timer) clearInterval(timer);
        };
    }, [isDeploying]);

    const handleDeploy = async (overrideDryRun = null) => {
        if (!target || isDeploying) return;
        const useDryRun = typeof overrideDryRun === 'boolean' ? overrideDryRun : dryRun;
        setIsDeploying(true);
        setStreamOutput('');
        setStreamResult(null);
        setStreamError(null);
        setElapsedSeconds(0);

        try {
            if (providersApi.deployStream) {
                await providersApi.deployStream(
                    {
                        target,
                        dry_run: useDryRun,
                        provider_id: provider?.id,
                    },
                    {
                        onChunk: (chunk) => {
                            setStreamOutput((prev) => prev + chunk);
                        },
                        onFinish: (result) => {
                            setIsDeploying(false);
                            setStreamResult(result);
                            queryClient.invalidateQueries({ queryKey: ['provider-logs', provider?.id] });
                            queryClient.invalidateQueries({ queryKey: ['providers'] });
                            queryClient.invalidateQueries({ queryKey: ['provider-status-cards'] });
                            if (result.ok) {
                                toast.success(`${details.label} deployed successfully!`);
                            } else {
                                toast.error(`Deployment failed (exit ${result.exit_code})`);
                            }
                        },
                        onError: (err) => {
                            setIsDeploying(false);
                            setStreamError(err.message);
                            toast.error(err.message || 'Deployment failed to start');
                        },
                    }
                );
            } else {
                const result = await providersApi.deploy({
                    target,
                    dry_run: useDryRun,
                    provider_id: provider?.id,
                });
                setIsDeploying(false);
                setStreamResult(result);
                setStreamOutput(result.output || '');
                queryClient.invalidateQueries({ queryKey: ['provider-logs', provider?.id] });
                queryClient.invalidateQueries({ queryKey: ['providers'] });
                queryClient.invalidateQueries({ queryKey: ['provider-status-cards'] });
                if (result.ok) {
                    toast.success(`${details.label} deployed successfully!`);
                } else {
                    toast.error(`Deployment failed (exit ${result.exit_code})`);
                }
            }
        } catch (err) {
            setIsDeploying(false);
            setStreamError(err.message);
            toast.error(err.message || 'Deployment failed to start');
        }
    };

    const handleDeployRef = useRef(handleDeploy);
    useEffect(() => {
        handleDeployRef.current = handleDeploy;
    });

    // Auto-attach if a deployment is currently running on the server
    const activeIsRunning = logsData?.active_deploy?.is_running;
    const activeDryRun = logsData?.active_deploy?.dry_run;
    useEffect(() => {
        if (activeIsRunning && !isDeploying && !streamResult) {
            const timeoutId = setTimeout(() => {
                handleDeployRef.current(activeDryRun);
            }, 0);
            return () => clearTimeout(timeoutId);
        }
    }, [activeIsRunning, activeDryRun, isDeploying, streamResult]);

    const handleCopyOutput = async (text) => {
        if (!text) return;
        const ok = await copyToClipboard(text);
        if (ok) {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    };

    // Output priority: active live stream > stream result > persisted backend logs
    const persistedDeploy = logsData?.deploy;
    const currentDeploy = streamResult || (!isDeploying ? persistedDeploy : null);
    const outputText =
        isDeploying || streamOutput
            ? streamOutput
            : (currentDeploy?.output || (streamError ? `Deployment error: ${streamError}` : ''));

    if (!target) {
        return (
            <div className="rounded-xl border border-white/10 bg-white/[0.02] p-6 text-center">
                <Rocket className="mx-auto mb-3 h-8 w-8 text-gray-500" />
                <h3 className="text-base font-semibold text-white">Not a Serverless Provider</h3>
                <p className="mt-1 text-sm text-gray-400">
                    Provider <code className="font-mono text-purple-300">{provider?.id}</code> uses transport{' '}
                    <code className="font-mono text-gray-300">{provider?.type}</code>, which connects directly to existing endpoints and does not require serverless code deployments.
                </p>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {logsIsError && (
                <div className="mb-4">
                    <QueryErrorState error={logsError} noun="deployment logs" onRetry={() => refetchLogs()} />
                </div>
            )}
            {/* Target & Worker Summary Card */}
            <div className="rounded-2xl border border-white/10 bg-gradient-to-br from-purple-950/20 via-gray-900/60 to-gray-950/80 p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="space-y-1">
                        <div className="flex items-center gap-2">
                            <span className="rounded bg-purple-500/20 px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-purple-300 border border-purple-500/30">
                                {details.transport}
                            </span>
                            <h3 className="text-base font-semibold text-white">{details.label}</h3>
                        </div>
                        <p className="text-xs text-gray-400">{details.description}</p>
                        <div className="mt-2 flex items-center gap-3 font-mono text-[11px] text-gray-400">
                            <span>Artifact: <span className="text-purple-300">{details.artifact}</span></span>
                            <span>•</span>
                            <span>Target: <span className="text-gray-300">{target}</span></span>
                        </div>
                    </div>

                    {/* Deploy Actions & Trigger */}
                    <div className="flex flex-col items-end gap-3">
                        <label className="flex cursor-pointer items-center gap-2 text-xs text-gray-300 select-none">
                            <input
                                type="checkbox"
                                checked={dryRun}
                                onChange={(e) => setDryRun(e.target.checked)}
                                disabled={isDeploying}
                                className="h-4 w-4 rounded border-gray-700 bg-gray-800 text-blue-600 focus:ring-0"
                            />
                            <span>Dry run (<code className="font-mono text-[11px] text-gray-400">--dry-run</code>)</span>
                        </label>

                        <button
                            type="button"
                            onClick={handleDeploy}
                            disabled={isDeploying}
                            className={`inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-semibold text-white shadow-lg transition-all ${
                                isDeploying
                                    ? 'bg-purple-600/50 cursor-not-allowed'
                                    : 'bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 hover:shadow-purple-500/25 active:scale-95'
                            }`}
                        >
                            {isDeploying ? (
                                <>
                                    <Loader2 className="h-4 w-4 animate-spin text-purple-200" />
                                    <span>Deploying ({elapsedSeconds}s)…</span>
                                </>
                            ) : (
                                <>
                                    <Rocket className="h-4 w-4" />
                                    <span>{dryRun ? 'Pre-flight Check' : `Deploy ${details.transport} Worker`}</span>
                                </>
                            )}
                        </button>
                    </div>
                </div>
            </div>

            {/* Execution / Output Section */}
            <div className="rounded-2xl border border-white/10 bg-gray-950/60 p-5 space-y-4">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <Terminal className="h-4 w-4 text-gray-400" />
                        <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-400">
                            Build & Deployment Console
                        </h4>
                        {isDeploying ? (
                            <span className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20">
                                <Loader2 size={12} className="animate-spin" />
                                <span>Streaming Live ({elapsedSeconds}s)</span>
                            </span>
                        ) : currentDeploy ? (
                            <span
                                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                                    currentDeploy.ok
                                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                        : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                                }`}
                            >
                                {currentDeploy.ok ? (
                                    <>
                                        <CheckCircle2 size={12} />
                                        <span>Exit {currentDeploy.exit_code ?? 0}</span>
                                    </>
                                ) : (
                                    <>
                                        <AlertCircle size={12} />
                                        <span>Failed (Exit {currentDeploy.exit_code ?? 1})</span>
                                    </>
                                )}
                            </span>
                        ) : null}
                        {currentDeploy?.timestamp && !isDeploying && (
                            <span className="text-[11px] text-gray-500">
                                {formatTimestamp(currentDeploy.timestamp)}
                            </span>
                        )}
                    </div>

                    <div className="flex items-center gap-2">
                        {logsLoading && (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-gray-500" />
                        )}
                        <button
                            type="button"
                            onClick={() => refetchLogs()}
                            className="rounded p-1 text-gray-400 hover:text-white transition-colors"
                            title="Refresh logs"
                        >
                            <RefreshCw size={14} />
                        </button>
                        {outputText && (
                            <button
                                type="button"
                                onClick={() => handleCopyOutput(outputText)}
                                className="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-white transition-colors px-2 py-1 rounded hover:bg-white/5"
                            >
                                {copied ? <CheckCircle2 size={12} className="text-emerald-400" /> : <Copy size={12} />}
                                <span>{copied ? 'Copied' : 'Copy Output'}</span>
                            </button>
                        )}
                    </div>
                </div>

                {isDeploying && (
                    <div className="flex items-center gap-3 rounded-xl border border-purple-500/30 bg-purple-950/20 p-4 text-xs text-purple-300">
                        <Loader2 className="h-5 w-5 animate-spin text-purple-400 flex-shrink-0" />
                        <div>
                            <p className="font-semibold">Deployment in progress…</p>
                            <p className="text-purple-300/80 mt-0.5">
                                Packaging worker code and streaming live output from {details.transport}. You can freely switch tabs or inspect other providers; the deployment continues on the server.
                            </p>
                        </div>
                    </div>
                )}

                {/* Terminal Monospace Output Block */}
                <div className="relative">
                    <pre
                        ref={consoleRef}
                        className="max-h-96 min-h-[160px] overflow-y-auto rounded-xl border border-black/40 bg-black/80 p-4 font-mono text-[11px] leading-relaxed text-gray-300 select-text whitespace-pre-wrap"
                    >
                        {outputText || (
                            <span className="italic text-gray-600">
                                No deployment output recorded yet. Click &quot;Deploy {details.transport} Worker&quot; above to initiate build.
                            </span>
                        )}
                    </pre>
                </div>
            </div>
        </div>
    );
}
