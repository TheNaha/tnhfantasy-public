import React, { useState } from 'react';
import { ChevronRight, Eye, Pin, PinOff, Scissors, Brain, Activity, Sparkles } from 'lucide-react';
import clsx from 'clsx';

/**
 * What a single reply was actually told.
 *
 * The gap this fills: `SystemPromptPanel` already shows the system prompt and
 * what each section of it contributed, but nothing showed the CONVERSATION —
 * which turns were sent, which were labelled as narration, which speaker each
 * one was attributed to, and what got pruned to fit the budget. A reply that
 * ignored something from three turns ago was indistinguishable from a reply that
 * had that text trimmed out of it entirely.
 *
 * The data is a digest captured at send time by
 * `context_builder.context_trace_digest` and carried on the job, so this is what
 * THIS reply saw — not what building the context again today would produce. That
 * distinction is the whole point: a reconstruction would be a different
 * conversation by the time you look at it.
 *
 * It is a digest and deliberately so. Char counts and labels, never the prose:
 * this lives on a message row, and a full copy of the payload would multiply
 * every reply's storage by the length of the conversation. The question a user
 * actually has — "was the narration labelled? did it see Bram's name? was my
 * message pruned?" — is answerable without a single word of the text.
 */

const ROLE_LABEL = {
    user: 'You',
    assistant: 'Assistant',
    system: 'System',
};

const ROLE_ICON = {
    user: '👤',
    assistant: '🤖',
    system: '⚙️',
};

const ROLE_COLOR = {
    user: 'text-sky-300 border-sky-500/25 bg-sky-500/10',
    assistant: 'text-violet-300 border-violet-500/25 bg-violet-500/10',
    system: 'text-amber-300 border-amber-500/25 bg-amber-500/10',
};

/** The first thing in a turn's text, so the reader can tell WHAT it was. */
function preview(turn) {
    const text = turn.label;
    if (!text) return null;
    const trimmed = text.length >= 60 ? `${text.slice(0, 59)}…` : text;
    return trimmed;
}

export default function ContextTracePanel({ trace, meta = {} }) {
    const [open, setOpen] = useState(false);
    const [showAll, setShowAll] = useState(false);

    if (!trace || typeof trace !== 'object') return null;

    const turns = Array.isArray(trace.turns) ? trace.turns : [];
    const sections = Array.isArray(trace.sections) ? trace.sections : [];
    const budgets = trace.budgets && typeof trace.budgets === 'object' ? trace.budgets : {};
    const speakers = trace.speakers || {};
    const config = trace.config || {};
    const dropped = Array.isArray(trace.dropped) ? trace.dropped : [];
    const decision = trace.director_decision && typeof trace.director_decision === 'object' ? trace.director_decision : null;
    const visible = showAll ? turns : turns.slice(-12);
    const hidden = turns.length - visible.length;

    const totalInputTokens = trace.total_input_tokens ?? trace.total_tokens ?? 0;
    const budgetTokens = trace.budget_tokens || 4096;
    const breakdown = trace.tokens_breakdown || {};
    const pctUsed = Math.min(100, Math.round((totalInputTokens / budgetTokens) * 100));
    const tokensOut = meta.token_usage?.completion_tokens ?? meta.completion_tokens ?? meta.tokens_out ?? null;

    return (
        <div className="mt-1 rounded-xl border border-white/10 bg-gray-900/40 overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors whitespace-nowrap overflow-hidden"
                aria-expanded={open}
            >
                <ChevronRight size={12} className={clsx("shrink-0 transition-transform", open && "rotate-90")} />
                <span className="font-medium text-gray-400 shrink-0">What this reply was told</span>
                {decision?.pacing_directive && (
                    <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300 text-3xs font-mono shrink-0"
                        title={`Director Pacing: ${decision.pacing_directive}`}
                    >
                        <span className="text-blue-400">⚡</span>
                        <span>{decision.pacing_directive}</span>
                        {(decision.scene_tension != null || decision.tension_level != null) && (
                            <span className="opacity-70">· T{decision.scene_tension ?? decision.tension_level}/5</span>
                        )}
                    </span>
                )}
                {tokensOut != null && (
                    <span
                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-3xs font-mono shrink-0"
                        title={`Generated ${tokensOut} output tokens`}
                    >
                        <span>⚡</span>
                        <span>{tokensOut} tok</span>
                    </span>
                )}

                <span className="ml-auto text-gray-600 font-mono text-3xs shrink-0 truncate">
                    {totalInputTokens > 0 ? `${totalInputTokens.toLocaleString()} / ${budgetTokens.toLocaleString()} tok · ` : ''}
                    {turns.length} turn{turns.length === 1 ? '' : 's'} · {sections.length} sections
                    {trace.truncated ? ' · truncated' : ''}
                </span>
            </button>

            {open && (
                <div className="border-t border-white/10 px-3 py-2.5 flex flex-col gap-3 text-xs">
                    {/* Visual Turn Lifecycle Rundown */}
                    <div className="rounded-xl border border-white/10 bg-gradient-to-br from-gray-900/90 via-purple-950/20 to-gray-900/90 p-3 space-y-2.5">
                        <div className="flex items-center justify-between pb-1.5 border-b border-white/5">
                            <span className="text-3xs font-bold uppercase tracking-wider text-purple-300 flex items-center gap-1.5">
                                <Activity size={11} className="text-purple-400" /> Turn Lifecycle Rundown
                            </span>
                            <span className="text-3xs font-mono text-gray-500">
                                {meta?.duration_seconds ? `${Number(meta.duration_seconds).toFixed(2)}s duration` : 'Full turn sequence'}
                            </span>
                        </div>
                        
                        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 text-3xs">
                            {/* Step 1: User Send */}
                            <div className="bg-sky-500/10 border border-sky-500/25 rounded-lg p-2 flex flex-col justify-between">
                                <div>
                                    <span className="text-sky-400 font-bold uppercase tracking-wider block mb-0.5">1. User Send</span>
                                    <span className="text-gray-200 font-medium">Player Input</span>
                                </div>
                                <span className="text-gray-400 font-mono text-3xs mt-1 truncate">
                                    {trace.user_directive ? `Dir: "${trace.user_directive}"` : 'Prompt received'}
                                </span>
                            </div>

                            {/* Step 2: System 1 Director */}
                            <div className="bg-purple-500/10 border border-purple-500/25 rounded-lg p-2 flex flex-col justify-between">
                                <div>
                                    <span className="text-purple-400 font-bold uppercase tracking-wider block mb-0.5">2. Director</span>
                                    <span className="text-gray-200 font-medium">Arbitration</span>
                                </div>
                                <span className="text-purple-300 font-mono text-3xs mt-1 truncate">
                                    {decision?.pacing_directive || 'Pacing set'} · T{decision?.scene_tension ?? 2}/5
                                </span>
                            </div>

                            {/* Step 3: Actor LLM */}
                            <div className="bg-emerald-500/10 border border-emerald-500/25 rounded-lg p-2 flex flex-col justify-between">
                                <div>
                                    <span className="text-emerald-400 font-bold uppercase tracking-wider block mb-0.5">3. Actor LLM</span>
                                    <span className="text-gray-200 font-medium">{meta?.source === 'narrator' ? 'Narrator' : 'Character AI'}</span>
                                </div>
                                <span className="text-emerald-300 font-mono text-3xs mt-1 truncate">
                                    {tokensOut != null ? `${tokensOut} tokens out` : 'Prose generated'}
                                </span>
                            </div>

                            {/* Step 4: Post-Turn Conductor */}
                            <div className="bg-amber-500/10 border border-amber-500/25 rounded-lg p-2 flex flex-col justify-between">
                                <div>
                                    <span className="text-amber-400 font-bold uppercase tracking-wider block mb-0.5">4. Conductor</span>
                                    <span className="text-gray-200 font-medium">Post-Response</span>
                                </div>
                                <span className="text-amber-300 font-mono text-3xs mt-1 truncate">
                                    {decision?.should_trigger_image ? 'Art triggered' : (decision?.gate_durable_memory ? 'Memory gated' : 'Evaluated')}
                                </span>
                            </div>

                            {/* Step 5: Resolution */}
                            <div className="bg-indigo-500/10 border border-indigo-500/25 rounded-lg p-2 flex flex-col justify-between">
                                <div>
                                    <span className="text-indigo-400 font-bold uppercase tracking-wider block mb-0.5">5. Resolution</span>
                                    <span className="text-gray-200 font-medium">Next Turn</span>
                                </div>
                                <span className="text-indigo-300 font-mono text-3xs mt-1 truncate">
                                    {decision?.next_speaker && decision.next_speaker !== 'user'
                                        ? `Chained ${decision.next_speaker}`
                                        : 'Yielded to User'}
                                </span>
                            </div>
                        </div>
                    </div>


                    {/* Token Budget Meter */}
                    <div className="rounded-lg border border-white/10 bg-black/40 p-2.5 space-y-1.5">
                        <div className="flex items-center justify-between text-3xs font-mono">
                            <span className="text-gray-400 font-semibold uppercase tracking-wider">
                                Input Token Budget
                            </span>
                            <span className="text-gray-200 font-bold">
                                {totalInputTokens.toLocaleString()} <span className="text-gray-500 font-normal">/ {budgetTokens.toLocaleString()} tokens ({pctUsed}%)</span>
                            </span>
                        </div>
                        {/* Segmented Bar */}
                        <div className="w-full h-2 rounded-full bg-gray-800/80 overflow-hidden flex border border-white/5">
                            {breakdown.system > 0 && (
                                <div
                                    style={{ width: `${(breakdown.system / budgetTokens) * 100}%` }}
                                    className="bg-amber-400 h-full"
                                    title={`System: ${breakdown.system} tokens`}
                                />
                            )}
                            {breakdown.character > 0 && (
                                <div
                                    style={{ width: `${(breakdown.character / budgetTokens) * 100}%` }}
                                    className="bg-pink-400 h-full"
                                    title={`Character: ${breakdown.character} tokens`}
                                />
                            )}
                            {breakdown.lorebooks > 0 && (
                                <div
                                    style={{ width: `${(breakdown.lorebooks / budgetTokens) * 100}%` }}
                                    className="bg-emerald-400 h-full"
                                    title={`Lorebooks: ${breakdown.lorebooks} tokens`}
                                />
                            )}
                            {breakdown.state > 0 && (
                                <div
                                    style={{ width: `${(breakdown.state / budgetTokens) * 100}%` }}
                                    className="bg-purple-400 h-full"
                                    title={`State: ${breakdown.state} tokens`}
                                />
                            )}
                            {breakdown.turns > 0 && (
                                <div
                                    style={{ width: `${(breakdown.turns / budgetTokens) * 100}%` }}
                                    className="bg-sky-400 h-full"
                                    title={`Dialogue turns: ${breakdown.turns} tokens`}
                                />
                            )}
                        </div>
                        {/* Breakdown Legend */}
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-3xs text-gray-400 pt-0.5">
                            <span className="flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> System: <strong className="text-gray-300 font-mono">{breakdown.system ?? 0}</strong>
                            </span>
                            <span className="flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-pink-400" /> Character: <strong className="text-gray-300 font-mono">{breakdown.character ?? 0}</strong>
                            </span>
                            <span className="flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Lore: <strong className="text-gray-300 font-mono">{breakdown.lorebooks ?? 0}</strong>
                            </span>
                            <span className="flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-purple-400" /> State: <strong className="text-gray-300 font-mono">{breakdown.state ?? 0}</strong>
                            </span>
                            <span className="flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-sky-400" /> Dialogue: <strong className="text-gray-300 font-mono">{breakdown.turns ?? 0}</strong>
                            </span>
                        </div>
                    </div>

                    {trace.user_directive && (
                        <div className="rounded-lg border border-purple-500/30 bg-purple-950/30 px-2.5 py-1.5 flex items-center gap-2 text-xs text-purple-200">
                            <span className="font-bold text-3xs uppercase tracking-wider text-purple-400 shrink-0">🎯 Turn Directive:</span>
                            <span className="italic truncate">&ldquo;{trace.user_directive}&rdquo;</span>
                        </div>
                    )}

                    {decision && (
                        <div className="rounded-lg border border-purple-500/25 bg-purple-950/20 p-2.5 space-y-2">
                            <div className="flex items-center justify-between pb-1.5 border-b border-purple-500/20">
                                <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-purple-300 text-3xs">
                                    <Brain size={12} className="text-purple-400" />
                                    <span>Director Decision Snapshot</span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                    {decision.pacing_directive && (
                                        <span className="px-1.5 py-0.5 rounded bg-blue-500/20 border border-blue-500/30 text-blue-300 font-mono text-3xs">
                                            {decision.pacing_directive}
                                        </span>
                                    )}
                                    {(decision.scene_tension != null || decision.tension_level != null) && (
                                        <span className="px-1.5 py-0.5 rounded bg-amber-500/20 border border-amber-500/30 text-amber-300 font-mono text-3xs">
                                            Tension {decision.scene_tension ?? decision.tension_level}/5
                                        </span>
                                    )}
                                </div>
                            </div>
                            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-3xs text-gray-300">
                                <div>
                                    <span className="text-gray-500 block">Speaker</span>
                                    <span className="font-semibold text-gray-200">{decision.next_speaker || 'AI'}</span>
                                </div>
                                <div>
                                    <span className="text-gray-500 block">Emotional Tone</span>
                                    <span className="font-semibold text-purple-300">{decision.emotional_tone || 'neutral'}</span>
                                </div>
                                <div>
                                    <span className="text-gray-500 block">Expression</span>
                                    <span className="font-semibold text-amber-300">{decision.character_expression || decision.visual_expression || 'normal'}</span>
                                </div>
                                <div>
                                    <span className="text-gray-500 block">Fate Check</span>
                                    <span className={clsx(
                                        "font-semibold",
                                        decision.fate_outcome?.includes('success') ? "text-emerald-400" :
                                        decision.fate_outcome?.includes('fail') ? "text-rose-400" : "text-gray-400"
                                    )}>
                                        {decision.fate_outcome ? `${decision.fate_outcome} (DC ${decision.fate_dc || 12})` : (decision.fate_check_needed ? 'Needed' : 'None')}
                                    </span>
                                </div>
                            </div>
                            {decision.suggested_action_chips?.length > 0 && (
                                <div className="pt-1.5 border-t border-white/5 flex flex-wrap items-center gap-1.5 text-3xs">
                                    <span className="text-gray-500 font-medium">Continuation hints:</span>
                                    {decision.suggested_action_chips.map((chip, idx) => (
                                        <span key={idx} className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-gray-300">
                                            {chip}
                                        </span>
                                    ))}
                                </div>
                            )}
                            {decision.reasoning_summary && (
                                <p className="text-3xs text-gray-400 italic pt-1 border-t border-white/5">
                                    &ldquo;{decision.reasoning_summary}&rdquo;
                                </p>
                            )}
                        </div>
                    )}

                    {/* The mapping: was a narration labelled, were speakers named */}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-gray-500 text-3xs">
                        <span>
                            speakers:{' '}
                            <span className="text-gray-300 font-mono">
                                {speakers.count ?? 0}
                                {speakers.named?.length ? ` (${speakers.named.join(', ')})` : ''}
                            </span>
                        </span>
                        <span>
                            labelling:{' '}
                            <span className={config.label_speakers ? 'text-emerald-300' : 'text-gray-500'}>
                                {config.label_speakers ? 'names on' : 'names off'}
                            </span>
                        </span>
                        {config.narrator_prefix ? (
                            <span>
                                narration marker:{' '}
                                <span className="text-gray-300 font-mono">{config.narrator_prefix}</span>
                            </span>
                        ) : null}
                    </div>

                    {Object.keys(budgets).length > 0 && (
                        <div className="flex flex-wrap gap-2 text-gray-400 items-center">
                            <span className="text-3xs uppercase tracking-wider font-semibold text-gray-500">Autonomous Tools:</span>
                            {Object.entries(budgets).map(([name, budget]) => (
                                <span key={name} className="px-2 py-0.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 font-mono text-3xs">
                                    <span className="opacity-80">{name === 'generate_image' ? '🎨 ' : name === 'narrate_scene' ? '📖 ' : ''}</span>
                                    <span>{name}:</span> <span>{budget.spent ?? 0}/{budget.max}</span>
                                </span>
                            ))}
                        </div>
                    )}

                    <div>
                        <p className="text-2xs font-semibold uppercase tracking-wider text-gray-500 mb-1.5 flex items-center justify-between">
                            <span>Turns sent ({turns.length})</span>
                            <span className="text-3xs text-gray-600 normal-case">showing newest {visible.length}</span>
                        </p>
                        <div className="flex flex-col gap-1">
                            {visible.map((turn, idx) => {
                                const role = turn.role || '?';
                                const previewText = preview(turn);
                                return (
                                    <div
                                        key={turn.role + idx}
                                        className="flex items-baseline gap-2 px-2 py-1 rounded bg-gray-800/40 hover:bg-gray-800/70 transition-colors"
                                    >
                                        <span className={`shrink-0 px-1.5 py-px rounded border font-mono text-3xs ${ROLE_COLOR[role] || 'text-gray-400 border-gray-600 bg-gray-700/20'}`}>
                                            <span aria-hidden="true" className="mr-1">{ROLE_ICON[role] || '•'}</span>
                                            <span>{ROLE_LABEL[role] || role}</span>
                                        </span>
                                        {turn.kind && (
                                            <span className="shrink-0 text-pink-400/80 font-mono text-3xs px-1 rounded bg-pink-500/10 border border-pink-500/20">{turn.kind}</span>
                                        )}
                                        {previewText ? (
                                            <span className="truncate text-gray-300 font-mono text-xs" title={previewText}>"{previewText}"</span>
                                        ) : (
                                            <span className="text-gray-600 italic text-3xs">(empty turn)</span>
                                        )}
                                        <span className="ml-auto shrink-0 text-gray-500 font-mono tabular-nums text-3xs">
                                            {turn.chars ?? 0}c
                                        </span>
                                        {turn.pinned ? (
                                            <Pin size={10} className="shrink-0 text-amber-400/80" aria-label="pinned" />
                                        ) : (
                                            <PinOff size={10} className="shrink-0 text-gray-700" aria-label="prunable" />
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                        {hidden > 0 && (
                            <button
                                type="button"
                                onClick={() => setShowAll(true)}
                                className="mt-1 text-gray-500 hover:text-gray-300 underline"
                            >
                                show {hidden} earlier turn{hidden === 1 ? '' : 's'}
                            </button>
                        )}
                    </div>

                    <div>
                        <p className="text-2xs font-semibold uppercase tracking-wider text-gray-600 mb-1">
                            Prompt sections
                        </p>
                        <div className="flex flex-wrap gap-1">
                            {sections.map((sec, idx) => (
                                <span
                                    key={`${sec.label}-${idx}`}
                                    title={`${sec.source || 'unknown source'} · ${sec.chars ?? 0} characters`}
                                    className="inline-flex items-center gap-1 px-1.5 py-px rounded border border-white/10 bg-gray-800/40 text-gray-400 font-mono"
                                >
                                    {sec.label}
                                    <span className="text-gray-600">{sec.chars}</span>
                                </span>
                            ))}
                        </div>
                        <p className="mt-1 text-gray-600">
                            system prompt {trace.system_prompt_chars ?? 0}c · budget {trace.budget_tokens ?? 0} tok
                        </p>
                    </div>

                    {/* Which provider and model actually produced this reply.
                        The trace is built at send time and the provider is
                        assigned by the load balancer, so "why did this reply
                        differ from that one" was unanswerable from the message
                        alone — the prompts were comparable and the assignment was
                        recorded nowhere. Stamped at finalize. */}
                    {trace.execution && (trace.execution.provider_id || trace.execution.model) ? (
                        <p className="text-gray-500">
                            ran on{' '}
                            <span className="text-gray-300 font-mono">
                                {trace.execution.provider_id || 'unassigned'}
                            </span>
                            {trace.execution.model ? (
                                <>
                                    {' · '}
                                    <span className="text-gray-300 font-mono">{trace.execution.model}</span>
                                </>
                            ) : null}
                        </p>
                    ) : null}

                    {dropped.length > 0 && (
                        <p className="flex items-center gap-1.5 text-amber-300/80">
                            <Scissors size={11} />
                            {dropped.length} stored message{dropped.length === 1 ? '' : 's'} did not become turns
                            {dropped.includes('unknown') ? ' (not world-state)' : ''}
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}
