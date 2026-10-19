import React, { useState } from 'react';
import {
    Activity, Clock, ChevronDown, ChevronUp, Bot, Shield,
    Play, Sparkles, AlertCircle, RefreshCw, Layers
} from 'lucide-react';
import clsx from 'clsx';
import { useChats } from '../../hooks/useWorldVault';
import { useDirectorTraces } from '../../hooks/usePipeline';
import { formatTimestamp } from '../../utils/dateTime';

export default function DecisionTraceTab() {
    const { data: chats = [], isLoading: isLoadingChats } = useChats({ limit: 30 });
    const [selectedChatId, setSelectedChatId] = useState('');

    // Select the first chat if none selected
    const activeChatId = selectedChatId || (chats[0]?.id || '');

    const { data: traces = [], isLoading: isLoadingTraces, refetch } = useDirectorTraces(activeChatId);
    const [expandedTraceId, setExpandedTraceId] = useState(null);

    const toggleExpand = (id) => {
        setExpandedTraceId(expandedTraceId === id ? null : id);
    };

    return (
        <div className="space-y-6">
            {/* Header and Chat Picker */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 glass-panel p-6 rounded-2xl border border-white/10">
                <div>
                    <h3 className="text-xl font-bold text-white tracking-wide flex items-center gap-2">
                        <Activity size={20} className="text-cyan-400" />
                        Laya Decision Traces &amp; Telemetry
                    </h3>
                    <p className="text-xs text-gray-400 mt-1">
                        Inspect recorded System 1 routing decisions, sub-variant picks, Fate &amp; Skill checks, and gate activations per message turn.
                    </p>
                </div>

                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2">
                        <label className="text-2xs font-bold uppercase text-gray-400 shrink-0">Session:</label>
                        <select
                            value={activeChatId}
                            onChange={(e) => setSelectedChatId(e.target.value)}
                            disabled={isLoadingChats}
                            className="bg-gray-900 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-cyan-500/50 max-w-xs truncate disabled:opacity-50"
                        >
                            {isLoadingChats && <option value="">Loading sessions…</option>}
                            {chats.map((c) => (
                                <option key={c.id} value={c.id}>
                                    {c.name || 'Untitled Chat'} ({c.id.slice(0, 8)})
                                </option>
                            ))}
                        </select>
                    </div>

                    <button
                        type="button"
                        onClick={() => refetch()}
                        className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white transition-colors"
                        title="Refresh traces"
                    >
                        <RefreshCw size={14} className={isLoadingTraces ? "animate-spin" : ""} />
                    </button>
                </div>
            </div>

            {/* Traces List */}
            {traces.length === 0 ? (
                <div className="p-12 text-center rounded-2xl border border-white/5 bg-gray-900/40">
                    <AlertCircle size={32} className="mx-auto text-gray-600 mb-3" />
                    <h4 className="text-sm font-bold text-gray-300">No Decision Traces Recorded Yet</h4>
                    <p className="text-xs text-gray-500 mt-1 max-w-md mx-auto">
                        Send a message in this chat session to see Laya System 1 pre-generation triage, post-generation audit, and turn-chaining traces land here in real time.
                    </p>
                </div>
            ) : (
                <div className="space-y-3">
                    {traces.map((trace) => {
                        const isExpanded = expandedTraceId === trace.id;
                        const dec = trace.decision || {};
                        const dateStr = trace.created_at ? formatTimestamp(trace.created_at) : '';

                        return (
                            <div
                                key={trace.id}
                                className="rounded-2xl border border-white/10 bg-gray-900/60 overflow-hidden shadow-lg transition-all"
                            >
                                <div
                                    onClick={() => toggleExpand(trace.id)}
                                    className="p-4 flex items-center justify-between gap-4 cursor-pointer hover:bg-white/5 transition-colors"
                                >
                                    <div className="flex items-center gap-3">
                                        <span className={clsx(
                                            "px-2.5 py-1 rounded-lg text-2xs font-bold uppercase tracking-wider border",
                                            trace.stage === 'triage' ? "bg-blue-500/10 text-blue-400 border-blue-500/20" :
                                            trace.stage === 'audit' ? "bg-amber-500/10 text-amber-400 border-amber-500/20" :
                                            "bg-cyan-500/10 text-cyan-400 border-cyan-500/20"
                                        )}>
                                            {trace.stage}
                                        </span>

                                        <div>
                                            <div className="flex items-center gap-2">
                                                <span className="text-xs font-bold text-white capitalize">
                                                    Turn {trace.turn} • {trace.selected_agent || dec.selected_agent || 'Unknown Agent'}
                                                </span>
                                                {trace.selected_variant && (
                                                    <span className="px-2 py-0.5 rounded-full bg-purple-500/20 border border-purple-500/30 text-purple-300 text-2xs font-mono font-bold">
                                                        variant: {trace.selected_variant}
                                                    </span>
                                                )}
                                            </div>
                                            <p className="text-2xs text-gray-400 mt-0.5">
                                                {dec.pacing_directive && `Pacing: ${dec.pacing_directive} • `}
                                                {dec.emotional_tone && `Tone: ${dec.emotional_tone} • `}
                                                {trace.extra?.engine_used || dec.engine_used || 'laya'} ({Math.round(trace.extra?.latency_ms || dec.latency_ms || 0)}ms)
                                            </p>
                                        </div>
                                    </div>

                                    <div className="flex items-center gap-4">
                                        {dec.fate_outcome && (
                                            <span className={clsx(
                                                "px-2 py-0.5 rounded text-2xs font-bold uppercase",
                                                dec.fate_outcome === 'success' || dec.fate_outcome === 'triumph' ? "bg-emerald-500/20 text-emerald-300" :
                                                dec.fate_outcome === 'mixed' ? "bg-amber-500/20 text-amber-300" :
                                                "bg-red-500/20 text-red-300"
                                            )}>
                                                Fate: {dec.fate_outcome}
                                            </span>
                                        )}

                                        {dec.triggered_gates && dec.triggered_gates.length > 0 && (
                                            <span className="px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-2xs font-bold">
                                                {dec.triggered_gates.length} Gates Fired
                                            </span>
                                        )}

                                        <span className="text-2xs font-mono text-gray-500">{dateStr}</span>
                                        {isExpanded ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
                                    </div>
                                </div>

                                {isExpanded && (
                                    <div className="p-4 border-t border-white/5 bg-black/30 space-y-3 animate-in fade-in duration-150">
                                        {dec.director_instruction && (
                                            <div className="p-3 rounded-xl bg-purple-950/20 border border-purple-500/20 text-xs text-purple-200">
                                                <strong className="text-purple-300 block mb-0.5">Director Instruction:</strong>
                                                {dec.director_instruction}
                                            </div>
                                        )}

                                        {dec.fate_directive && (
                                            <div className="p-3 rounded-xl bg-amber-950/20 border border-amber-500/20 text-xs text-amber-200">
                                                <strong className="text-amber-300 block mb-0.5">Fate &amp; Skill Directive:</strong>
                                                {dec.fate_directive}
                                            </div>
                                        )}

                                        {dec.triggered_gates && dec.triggered_gates.length > 0 && (
                                            <div>
                                                <span className="text-2xs font-bold uppercase text-gray-400 block mb-1.5">
                                                    Fired Narrative Gates (Updater Permitted Fields):
                                                </span>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {dec.triggered_gates.map((g) => (
                                                        <span key={g} className="px-2 py-0.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-2xs font-mono font-semibold">
                                                            {g}
                                                        </span>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        <details className="mt-2 text-2xs text-gray-400">
                                            <summary className="cursor-pointer font-bold text-gray-300 hover:text-white">
                                                View Complete Decision Payload JSON
                                            </summary>
                                            <pre className="mt-2 p-3 rounded-xl bg-gray-950 border border-white/5 overflow-x-auto text-2xs text-gray-300 font-mono">
                                                {JSON.stringify(dec, null, 2)}
                                            </pre>
                                        </details>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
