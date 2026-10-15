import { useEffect, useRef, useState } from 'react';
import {
    AlertCircle,
    Check,
    CheckCircle2,
    Clock,
    Copy,
    RefreshCw,
    Rocket,
    Terminal,
    X,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { useQueryClient } from '@tanstack/react-query';
import { ModalOverlay } from '../common/ModalOverlay';
import { copyToClipboard } from '../../utils/clipboard';
import { providersApi } from '../../api';


const TARGET_OPTIONS = [
    {
        id: 'image',
        label: 'Modal ComfyUI (Image)',
        artifact: 'comfy-modal-stack',
        transport: 'modal',
        desc: 'Deployables under deployables/modal/image/ (ComfyUI serverless)',
    },
    {
        id: 'tts',
        label: 'Modal TTS (Audio)',
        artifact: 'comfy-modal-tts',
        transport: 'modal',
        desc: 'Deployables under deployables/modal/tts/ (ChatTTS serverless)',
    },
    {
        id: 'llm',
        label: 'Modal LLM (Language)',
        artifact: 'tnh-llm',
        transport: 'modal',
        desc: 'Deployables under deployables/modal/llm/ (llama.cpp serverless)',
    },
    {
        id: 'beam',
        label: 'Beam Deployments',
        artifact: 'All four Beam apps',
        transport: 'beam',
        desc: 'Deployables under deployables/beam/ (Image, LLM, TTS)',
    },
    {
        id: 'all',
        label: 'All Targets',
        artifact: 'Modal + Beam workers',
        transport: 'modal+beam',
        desc: 'Deploy all serverless workers in sequence',
    },
];

function useSafeQueryClient() {
    try {
        return useQueryClient();
    } catch {
        return null;
    }
}

export default function DeployModal({
    isOpen = true,
    onClose,
    initialTarget = 'image',
    initialProviderId = null,
    providers = [],
}) {
    const queryClient = useSafeQueryClient();
    const [target, setTarget] = useState(initialTarget);
    const [selectedProviderId, setSelectedProviderId] = useState(initialProviderId || '');
    const [dryRun, setDryRun] = useState(false);
    const [status, setStatus] = useState('idle'); // 'idle' | 'running' | 'success' | 'failed'
    const [result, setResult] = useState(null);
    const [errorMsg, setErrorMsg] = useState(null);
    const [elapsedSeconds, setElapsedSeconds] = useState(0);
    const [copied, setCopied] = useState(false);
    const terminalRef = useRef(null);

    // Timer while running
    useEffect(() => {
        if (status !== 'running') return;
        const timer = setInterval(() => {
            setElapsedSeconds((s) => s + 1);
        }, 1000);
        return () => clearInterval(timer);
    }, [status]);

    // Scroll output to bottom when output arrives
    useEffect(() => {
        if (terminalRef.current) {
            terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
        }
    }, [result]);

    const handleDeploy = async () => {
        setStatus('running');
        setElapsedSeconds(0);
        setResult(null);
        setErrorMsg(null);
        setCopied(false);

        try {
            const payload = {
                target,
                dry_run: dryRun,
                timeout: 300,
            };
            if (selectedProviderId) {
                payload.provider_id = selectedProviderId;
            }

            const res = await providersApi.deploy(payload);
            setResult(res);
            if (res.ok) {
                setStatus('success');
                toast.success(`Deploy of ${target} completed successfully`);
            } else {
                setStatus('failed');
                toast.error(`Deploy of ${target} failed with exit code ${res.exit_code}`);
            }
            queryClient?.invalidateQueries({ queryKey: ['provider-logs'] });
            queryClient?.invalidateQueries({ queryKey: ['provider-diagnostics'] });
            queryClient?.invalidateQueries({ queryKey: ['providers'] });
        } catch (err) {
            setStatus('failed');
            const msg = err?.response?.data?.message || err?.message || 'Deployment failed';
            setErrorMsg(msg);
            toast.error(`Deploy error: ${msg}`);
        }
    };

    const handleCopy = async () => {
        const textToCopy = result?.output || errorMsg || '';
        if (!textToCopy) return;
        const ok = await copyToClipboard(textToCopy);
        if (ok) {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
            toast.success('Logs copied to clipboard');
        }
    };

    const currentTargetMeta = TARGET_OPTIONS.find((t) => t.id === target) || TARGET_OPTIONS[0];

    return (
        <ModalOverlay isOpen={isOpen} onClose={status === 'running' ? undefined : onClose} className="z-[70] bg-black/85 backdrop-blur-sm">
            <div
                role="dialog"
                aria-modal="true"
                aria-label="Deploy Cloud Worker"
                className="bg-gray-900 border border-gray-700/80 rounded-2xl w-full max-w-2xl flex flex-col max-h-[90vh] shadow-2xl overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="p-5 border-b border-gray-800 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="p-2 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
                            <Rocket size={20} />
                        </div>
                        <div>
                            <h2 className="text-lg font-bold text-white flex items-center gap-2">
                                {initialProviderId ? `Deploy ${currentTargetMeta.label}` : 'Deploy Cloud Worker'}
                            </h2>
                            <p className="text-xs text-gray-400 mt-0.5">
                                {initialProviderId ? `Target locked to ${initialProviderId} (${currentTargetMeta.artifact})` : 'Run scripts/deploy.sh from the backend host'}
                            </p>
                        </div>
                    </div>
                    {status !== 'running' && (
                        <button
                            type="button"
                            onClick={onClose}
                            className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors"
                            aria-label="Close deploy dialog"
                        >
                            <X size={18} />
                        </button>
                    )}
                </div>

                {/* Content */}
                <div className="p-5 overflow-y-auto space-y-4 flex-1">
                    {/* Status Banners */}
                    {status === 'running' && (
                        <div className="flex items-center justify-between p-4 rounded-xl bg-blue-950/40 border border-blue-800/40 text-blue-200 text-sm">
                            <div className="flex items-center gap-3">
                                <RefreshCw className="h-5 w-5 animate-spin text-blue-400" />
                                <div>
                                    <p className="font-semibold text-white">Deploying {currentTargetMeta.label}…</p>
                                    <p className="text-xs text-blue-300/80 mt-0.5">
                                        Building container and pushing image to cloud provider. This may take up to 2-3 minutes.
                                    </p>
                                </div>
                            </div>
                            <div className="flex items-center gap-1.5 font-mono text-xs text-blue-300 bg-blue-900/50 px-2.5 py-1 rounded-md">
                                <Clock size={13} />
                                {elapsedSeconds}s
                            </div>
                        </div>
                    )}

                    {status === 'success' && (
                        <div className="flex items-center justify-between p-4 rounded-xl bg-emerald-950/40 border border-emerald-800/40 text-emerald-200 text-sm">
                            <div className="flex items-center gap-3">
                                <CheckCircle2 className="h-5 w-5 text-emerald-400 flex-shrink-0" />
                                <div>
                                    <p className="font-semibold text-white">Deployment Succeeded</p>
                                    <p className="text-xs text-emerald-300/80 mt-0.5">
                                        Target {target} ({result?.artifact}) deployed in {result?.elapsed_seconds ?? elapsedSeconds}s
                                    </p>
                                </div>
                            </div>
                            <span className="text-xs font-mono bg-emerald-900/50 text-emerald-300 px-2.5 py-1 rounded-md">
                                Exit 0
                            </span>
                        </div>
                    )}

                    {status === 'failed' && (
                        <div className="flex items-center justify-between p-4 rounded-xl bg-rose-950/40 border border-rose-800/40 text-rose-200 text-sm">
                            <div className="flex items-center gap-3">
                                <AlertCircle className="h-5 w-5 text-rose-400 flex-shrink-0" />
                                <div>
                                    <p className="font-semibold text-white">Deployment Failed</p>
                                    <p className="text-xs text-rose-300/80 mt-0.5">
                                        {errorMsg || `Process exited with code ${result?.exit_code ?? 'unknown'}`}
                                    </p>
                                </div>
                            </div>
                            {result?.exit_code !== undefined && (
                                <span className="text-xs font-mono bg-rose-900/50 text-rose-300 px-2.5 py-1 rounded-md">
                                    Exit {result.exit_code}
                                </span>
                            )}
                        </div>
                    )}

                    {/* Target Selection & Configuration (when not running or after completion) */}
                    {status !== 'running' && (
                        <div className="space-y-4 rounded-xl bg-gray-800/50 border border-gray-700/50 p-4">
                            {initialProviderId ? (
                                <div className="rounded-xl bg-purple-950/30 border border-purple-500/30 p-3.5 flex items-center justify-between">
                                    <div>
                                        <div className="text-xs uppercase tracking-wider font-semibold text-purple-300">
                                            Target Worker
                                        </div>
                                        <div className="text-sm font-bold text-white mt-0.5">
                                            {currentTargetMeta.label} ({currentTargetMeta.artifact})
                                        </div>
                                        <div className="text-xs text-gray-400 mt-0.5">
                                            {currentTargetMeta.desc}
                                        </div>
                                    </div>
                                    <span className="text-xs font-mono px-2.5 py-1 bg-purple-900/50 text-purple-200 rounded-lg border border-purple-500/30 capitalize">
                                        {currentTargetMeta.transport}
                                    </span>
                                </div>
                            ) : (
                                <div>
                                    <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
                                        Deploy Target
                                    </label>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                        {TARGET_OPTIONS.map((opt) => (
                                            <button
                                                key={opt.id}
                                                type="button"
                                                onClick={() => setTarget(opt.id)}
                                                className={`p-3 rounded-xl border text-left transition-all ${
                                                    target === opt.id
                                                        ? 'bg-purple-950/40 border-purple-500/60 shadow-sm'
                                                        : 'bg-gray-800/80 border-gray-700/70 hover:border-gray-600'
                                                }`}
                                            >
                                                <div className="font-semibold text-sm text-white">{opt.label}</div>
                                                <div className="text-xs text-gray-400 mt-1">{opt.desc}</div>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {/* Provider Credentials Injection */}
                            {!initialProviderId && providers.length > 0 && (
                                <div>
                                    <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1">
                                        Authenticate With Credentials From:
                                    </label>
                                    <select
                                        value={selectedProviderId}
                                        onChange={(e) => setSelectedProviderId(e.target.value)}
                                        className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-xs text-white outline-none focus:border-purple-500"
                                    >
                                        <option value="">(Auto-select matching provider)</option>
                                        {providers.map((p) => (
                                            <option key={p.id} value={p.id}>
                                                {p.id} ({p.type} - {p.worker_type || 'image'})
                                            </option>
                                        ))}
                                    </select>
                                </div>
                            )}


                            {/* Dry run switch */}
                            <label className="flex items-center gap-2.5 text-xs text-gray-300 cursor-pointer pt-1">
                                <input
                                    type="checkbox"
                                    checked={dryRun}
                                    onChange={(e) => setDryRun(e.target.checked)}
                                    className="rounded border-gray-700 bg-gray-900 text-purple-600 focus:ring-purple-500"
                                />
                                <span>Dry run (<code className="font-mono text-purple-300">--dry-run</code>) — check configuration without deploying</span>
                            </label>
                        </div>
                    )}

                    {/* Terminal Output Viewer */}
                    {(result?.output || errorMsg) && (
                        <div className="space-y-1.5">
                            <div className="flex items-center justify-between">
                                <span className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
                                    <Terminal size={14} className="text-purple-400" />
                                    Captured Output
                                </span>
                                <button
                                    type="button"
                                    onClick={handleCopy}
                                    className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 px-2.5 py-1 rounded-md border border-gray-700 transition-colors"
                                >
                                    {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                                    {copied ? 'Copied' : 'Copy Output'}
                                </button>
                            </div>
                            <div
                                ref={terminalRef}
                                className="bg-[#0B0E14] border border-gray-800 rounded-xl p-3.5 max-h-72 overflow-y-auto overflow-x-auto text-xs font-mono text-gray-300 whitespace-pre-wrap select-text leading-relaxed"
                            >
                                {result?.output || errorMsg}
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="p-4 border-t border-gray-800 bg-gray-900/60 flex items-center justify-end gap-3">
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={status === 'running'}
                        className="px-4 py-2 rounded-xl text-xs font-medium text-gray-300 hover:bg-gray-800 disabled:opacity-50 transition-colors"
                    >
                        {status === 'success' ? 'Done' : 'Cancel'}
                    </button>
                    {status !== 'running' && (
                        <button
                            type="button"
                            onClick={handleDeploy}
                            className="inline-flex items-center gap-2 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white px-5 py-2.5 rounded-xl text-xs font-bold shadow-lg shadow-purple-600/20 transition-all active:scale-95"
                        >
                            <Rocket size={14} />
                            {status === 'idle' ? 'Start Deploy' : 'Deploy Again'}
                        </button>
                    )}
                </div>
            </div>
        </ModalOverlay>
    );
}
