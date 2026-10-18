import React, { useState } from 'react';
import clsx from 'clsx';
import {
    Brain, Sparkles, ChevronDown, ChevronUp, Clock, MapPin, Shield, Zap,
    Gauge, Activity, Compass, Dices, Layers
} from 'lucide-react';

const TENSION_COLOR = {
    calm: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    normal: 'text-sky-400 bg-sky-500/10 border-sky-500/20',
    rising: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    high: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
    climactic: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
};

const FATE_OUTCOME_STYLE = {
    critical_success: 'text-emerald-300 bg-emerald-500/20 border-emerald-500/30',
    success: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    success_with_cost: 'text-amber-300 bg-amber-500/20 border-amber-500/30',
    complication: 'text-orange-400 bg-orange-500/15 border-orange-500/25',
    failure: 'text-rose-400 bg-rose-500/20 border-rose-500/30',
};

export default function DirectorReasoningHUD({ jobData, pendingSpeaker }) {
    const [expanded, setExpanded] = useState(false);
    const decision = jobData?.directorDecision;

    return (
        <div className="mb-2 rounded-xl border border-white/10 bg-gray-900/80 backdrop-blur-md overflow-hidden text-xs shadow-lg transition-all duration-300">
            {/* Live Telemetry Header Bar */}
            <div className="px-3 py-2 flex flex-wrap items-center justify-between gap-2 border-b border-white/5 bg-black/30">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-3xs font-bold uppercase tracking-wider">
                        <Brain size={12} className="animate-pulse text-emerald-400" />
                        <span>Director &amp; Reasoning</span>
                    </span>

                    {decision?.pacing_directive && (
                        <span className="px-2 py-0.5 rounded-full bg-blue-500/15 border border-blue-500/25 text-blue-300 text-3xs font-medium">
                            Pacing: <span className="font-semibold">{decision.pacing_directive}</span>
                        </span>
                    )}

                    {decision?.scene_tension != null && (
                        <span className={clsx("px-2 py-0.5 rounded-full border text-3xs font-medium", TENSION_COLOR[decision.scene_tension_label] || TENSION_COLOR.normal)}>
                            Tension: <span className="font-semibold">{decision.scene_tension}/5 ({decision.scene_tension_label})</span>
                        </span>
                    )}

                    {decision?.emotional_tone && (
                        <span className="px-2 py-0.5 rounded-full bg-purple-500/15 border border-purple-500/25 text-purple-300 text-3xs font-medium hidden sm:inline-flex">
                            Tone: {decision.emotional_tone}
                        </span>
                    )}
                </div>

                <div className="flex items-center gap-2">
                    {/* Token Speedometer */}
                    {jobData?.speedTps ? (
                        <span className="flex items-center gap-1 font-mono text-3xs text-emerald-400">
                            <Zap size={11} className="animate-bounce" />
                            {jobData.speedTps} tok/s
                        </span>
                    ) : (
                        <span className="flex items-center gap-1 text-3xs text-blue-400/80">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                            {jobData?.phase === 'evaluating_prompt' ? 'Evaluating prompt...' : 'Synthesizing...'}
                        </span>
                    )}

                    {decision && (
                        <button
                            type="button"
                            onClick={() => setExpanded(v => !v)}
                            className="p-1 rounded text-gray-400 hover:text-white hover:bg-white/5 transition-colors flex items-center gap-0.5 text-3xs"
                            title="Toggle detailed decision telemetry"
                        >
                            <span>{expanded ? 'Less' : 'Details'}</span>
                            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                        </button>
                    )}
                </div>
            </div>

            {/* Quick Context Summary Row */}
            <div className="px-3 py-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-3xs text-gray-400 bg-white/[0.02]">
                <span>
                    Speaker: <strong className="text-gray-200">{decision?.next_speaker || pendingSpeaker?.name || 'Character'}</strong>
                </span>
                {decision?.character_expression && (
                    <span>
                        Expression: <strong className="text-amber-300">{decision.character_expression}</strong>
                    </span>
                )}
                {decision?.character_mood && (
                    <span>
                        Mood: <strong className="text-pink-300">{decision.character_mood.replace(/_/g, ' ')}</strong>
                    </span>
                )}
                {decision?.affinity_delta != null && decision.affinity_delta !== 0 && (
                    <span>
                        Affinity:{' '}
                        <strong className={decision.affinity_delta > 0 ? "text-emerald-400" : "text-rose-400"}>
                            {decision.affinity_delta > 0 ? `+${decision.affinity_delta}` : decision.affinity_delta}
                        </strong>
                    </span>
                )}
                {jobData?.providerId && (
                    <span>
                        Worker: <strong className="font-mono text-sky-300">{jobData.providerId}</strong>
                    </span>
                )}
                {decision?.fate_check_resolved && (
                    <span className="flex items-center gap-1">
                        <Dices size={10} className="text-amber-400" />
                        Fate Check:{' '}
                        <span className={clsx("px-1.5 py-0.2 rounded border font-semibold", FATE_OUTCOME_STYLE[decision.fate_outcome] || 'text-gray-300')}>
                            {decision.fate_outcome || 'Checked'}
                        </span>
                    </span>
                )}
            </div>

            {/* Expandable 13-Decision Breakdown */}
            {expanded && decision && (
                <div className="p-3 border-t border-white/5 bg-black/40 space-y-3 animate-in fade-in slide-in-from-top-1 duration-200">
                    <div className="grid gap-2.5 sm:grid-cols-3">
                        {/* 1. Turn & Pacing */}
                        <div className="p-2.5 rounded-lg bg-gray-900/70 border border-white/5 space-y-1 text-3xs">
                            <div className="font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1 pb-1 border-b border-white/5">
                                <Compass size={11} className="text-blue-400" />
                                Turn &amp; Pacing
                            </div>
                            <div className="text-gray-300"><b>Speaker:</b> <span className="text-emerald-300">{decision.next_speaker}</span></div>
                            <div className="text-gray-300"><b>Directive:</b> <span className="text-blue-300">{decision.pacing_directive}</span></div>
                            <div className="text-gray-300"><b>Speed:</b> {decision.pacing_speed_label} ({decision.pacing_speed}/4)</div>
                            <div className="text-gray-300"><b>Tone:</b> <span className="text-purple-300">{decision.emotional_tone}</span></div>
                            <div className="text-gray-300"><b>Continue Chain:</b> {Math.round((decision.continue_chain_prob || 0) * 100)}%</div>
                        </div>

                        {/* 2. Visuals & Fate Check */}
                        <div className="p-2.5 rounded-lg bg-gray-900/70 border border-white/5 space-y-1 text-3xs">
                            <div className="font-bold uppercase tracking-wider text-gray-400 flex items-center gap-1 pb-1 border-b border-white/5">
                                <Sparkles size={11} className="text-amber-400" />
                                Visuals &amp; Fate
                            </div>
                            <div className="text-gray-300"><b>Expression:</b> <span className="text-amber-300">{decision.character_expression}</span></div>
                            <div className="text-gray-300"><b>Image Focus:</b> {decision.image_focus}</div>
                            <div className="text-gray-300"><b>Trigger Image:</b> {Math.round((decision.trigger_image_prob || 0) * 100)}%</div>
                            <div className="text-gray-300">
                                <b>Action Risk:</b>{' '}
                                <span className={decision.is_risky_action_probability >= 0.5 ? 'text-amber-400 font-semibold' : 'text-gray-400'}>
                                    {Math.round((decision.is_risky_action_probability || 0) * 100)}% ({decision.action_difficulty_label || 'normal'})
                                </span>
                            </div>
                            {decision.director_instruction && (
                                <div className="mt-1 pt-1 border-t border-white/5 text-gray-400 italic">
                                    &ldquo;{decision.director_instruction}&rdquo;
                                </div>
                            )}
                        </div>

                        {/* 3. Statekeeper Gates */}
                        <div className="p-2.5 rounded-lg bg-gray-900/70 border border-white/5 space-y-1.5 text-3xs">
                            <div className="font-bold uppercase tracking-wider text-gray-400 flex items-center justify-between pb-1 border-b border-white/5">
                                <span className="flex items-center gap-1">
                                    <Shield size={11} className="text-purple-400" />
                                    Statekeeper Gates
                                </span>
                                <span className={clsx("px-1.5 py-0.5 rounded text-3xs font-bold", decision.should_run_updater ? "bg-purple-500/20 text-purple-300" : "bg-gray-800 text-gray-500")}>
                                    {decision.should_run_updater ? "FIRES" : "IDLE"}
                                </span>
                            </div>
                            {[
                                ['Location / Time', decision.updater_gates?.gate_world_state],
                                ['Char / Outfit / Rel', decision.updater_gates?.gate_character_state],
                                ['Inventory / Items', decision.updater_gates?.gate_inventory_or_items],
                                ['Durable Memory', decision.updater_gates?.gate_durable_memory],
                                ['Lore Discovery', decision.updater_gates?.gate_lore_discovery],
                            ].map(([label, prob]) => {
                                const pct = Math.round((prob || 0) * 100);
                                const active = (prob || 0) >= 0.55;
                                return (
                                    <div key={label} className="space-y-0.5">
                                        <div className="flex justify-between">
                                            <span className={active ? 'text-purple-300 font-semibold' : 'text-gray-400'}>{label}</span>
                                            <span className="font-mono text-gray-500">{pct}%</span>
                                        </div>
                                        <div className="w-full h-1 bg-gray-800 rounded-full overflow-hidden">
                                            <div
                                                className={clsx("h-full rounded-full transition-all duration-300", active ? "bg-gradient-to-r from-purple-500 to-indigo-400" : "bg-gray-700")}
                                                style={{ width: `${pct}%` }}
                                            />
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
