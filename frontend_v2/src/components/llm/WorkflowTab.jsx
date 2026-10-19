import React from 'react';
import {
    GitBranch, ArrowRight, Shield, Zap, Sparkles, Sliders,
    CheckCircle2, Clock, Play, User, Bot, BookOpen, Image as ImageIcon
} from 'lucide-react';
import clsx from 'clsx';
import { usePipeline } from '../../hooks/usePipeline';
import { useLLMCatalog } from '../../hooks/useLLMProviderStatus';

const STAGE_ICONS = {
    triage: GitBranch,
    act: Bot,
    audit: Shield,
    update: Zap,
    illustrate: ImageIcon,
    chain: Play,
};

const STAGE_COLORS = {
    triage: 'border-blue-500/30 bg-blue-500/5 text-blue-400',
    act: 'border-purple-500/30 bg-purple-500/5 text-purple-400',
    audit: 'border-amber-500/30 bg-amber-500/5 text-amber-400',
    update: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-400',
    illustrate: 'border-pink-500/30 bg-pink-500/5 text-pink-400',
    chain: 'border-cyan-500/30 bg-cyan-500/5 text-cyan-400',
};

export default function WorkflowTab() {
    const { data: pipeline, isLoading } = usePipeline();
    const catalog = useLLMCatalog();

    const stages = pipeline?.stages || [];
    const limits = pipeline?.limits || {};

    const activeModels = catalog.data?.active || {};

    if (isLoading && !pipeline) {
        return (
            <div className="flex flex-col items-center justify-center p-12 text-center">
                <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-3" />
                <span className="text-xs text-gray-400 font-medium">Loading pipeline manifest…</span>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header & Metrics */}
            <div className="glass-panel p-6 rounded-2xl border border-white/10 bg-gradient-to-r from-blue-950/20 via-purple-950/20 to-transparent">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-2xs font-bold uppercase tracking-wider mb-2">
                            <Sparkles size={12} />
                            Canonical 6-Stage Roleplay Pipeline
                        </div>
                        <h3 className="text-xl font-bold text-white tracking-wide">Multi-Agent Workflow Architecture</h3>
                        <p className="text-xs text-gray-400 mt-1 max-w-2xl">
                            Laya System 1 operates strictly as a router and conductor — it never writes character state directly. State updates and avatar expressions are owned by the Updater Agent, and visual workflows are handled by the Illustrator Agent.
                        </p>
                    </div>

                    <div className="flex items-center gap-3 shrink-0">
                        <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-center">
                            <span className="text-2xs text-gray-400 uppercase font-bold block">Autonomous Turns</span>
                            <span className="text-lg font-black text-blue-400">{limits.max_autonomous_turns || 4} turns</span>
                        </div>
                        <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-center">
                            <span className="text-2xs text-gray-400 uppercase font-bold block">Continuation Cap</span>
                            <span className="text-lg font-black text-purple-400">{limits.max_continuations || 4} repeats</span>
                        </div>
                        <div className="p-3 rounded-xl bg-white/5 border border-white/10 text-center">
                            <span className="text-2xs text-gray-400 uppercase font-bold block">Gate Threshold</span>
                            <span className="text-lg font-black text-emerald-400">{limits.gate_threshold || 0.55}</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Stage Flowchart */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {stages.map((stage, idx) => {
                    const Icon = STAGE_ICONS[stage.id] || Sparkles;
                    const colorClass = STAGE_COLORS[stage.id] || 'border-white/10 bg-white/5 text-gray-300';
                    const activeModel =
                        stage.target_role === 'director' ? (activeModels.decisions || 'Laya / Multilingual') :
                        stage.target_role === 'rp' ? (activeModels.rp || 'Auto RP') :
                        stage.target_role === 'util' ? (activeModels.util || 'Auto Util') :
                        'Default';

                    return (
                        <div
                            key={stage.id}
                            className={clsx(
                                "relative flex flex-col justify-between p-5 rounded-2xl border transition-all duration-300 hover:scale-[1.01] shadow-lg",
                                colorClass
                            )}
                        >
                            <div>
                                <div className="flex items-center justify-between mb-3">
                                    <div className="flex items-center gap-2.5">
                                        <div className="p-2 rounded-xl bg-white/10">
                                            <Icon size={18} />
                                        </div>
                                        <div>
                                            <span className="text-2xs font-bold uppercase tracking-wider text-gray-400 block">
                                                Stage {idx + 1} • {(stage.owner || stage.id || stage.stage || 'STAGE').toUpperCase()}
                                            </span>
                                            <h4 className="text-sm font-bold text-white">{stage.name}</h4>
                                        </div>
                                    </div>
                                    <span className="px-2 py-0.5 rounded text-2xs font-bold uppercase bg-white/10 text-gray-300 border border-white/10">
                                        {stage.target_role || stage.model_target || 'DIRECTOR'}
                                    </span>
                                </div>

                                <p className="text-xs text-gray-300/90 leading-relaxed mb-4">
                                    {stage.description}
                                </p>
                            </div>

                            <div className="pt-3 border-t border-white/10 flex items-center justify-between text-2xs text-gray-400">
                                <span className="flex items-center gap-1 font-mono">
                                    Model: <span className="text-white font-semibold">{activeModel}</span>
                                </span>
                                {stage.limits?.max_output_tokens && (
                                    <span>Max: {stage.limits.max_output_tokens} tok</span>
                                )}
                                {stage.limits?.timeout_ms && (
                                    <span>Timeout: {stage.limits.timeout_ms / 1000}s</span>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Workflow Pipeline Trace / Lifecycle Map */}
            <div className="glass-panel p-6 rounded-2xl border border-white/10 bg-gray-950/40">
                <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                    <Clock size={16} className="text-blue-400" />
                    Turn Lifecycle & Race Condition Guard
                </h4>
                <div className="space-y-3 text-xs text-gray-300 leading-relaxed">
                    <div className="p-3 rounded-xl bg-white/5 border border-white/5 flex items-start gap-3">
                        <span className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-300 font-bold shrink-0">1. Triage</span>
                        <span>User sends message. Laya evaluates speaker options, sub-variant selection (personality tags/hints), and runs the <strong>Fate &amp; Skill check</strong> for anti-godmoding.</span>
                    </div>
                    <div className="p-3 rounded-xl bg-white/5 border border-white/5 flex items-start gap-3">
                        <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 font-bold shrink-0">2. Actor</span>
                        <span>The selected actor (Character, Narrator, or Custom Agent) generates a turn with the resolved prompt template and scene directives. If truncated by token limit (<code>finish_reason=length</code>), continuation triggers seamlessly without counting against the 4-turn limit.</span>
                    </div>
                    <div className="p-3 rounded-xl bg-white/5 border border-white/5 flex items-start gap-3">
                        <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 font-bold shrink-0">3. Audit</span>
                        <span>Laya inspects the generated output and evaluates the 16 fine-grained narrative state gates and image generation threshold.</span>
                    </div>
                    <div className="p-3 rounded-xl bg-white/5 border border-white/5 flex items-start gap-3">
                        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-bold shrink-0">4. Update &amp; Chain</span>
                        <span><strong>Race Prevention:</strong> If state gates fired, the Updater agent runs first to update state snapshot, avatar expression, and location/time. Turn chaining evaluates <em>after</em> the Updater completes to guarantee the next speaker sees updated state.</span>
                    </div>
                </div>
            </div>
        </div>
    );
}
