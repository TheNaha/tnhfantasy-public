import React, { useState } from 'react';
import { ChevronRight, Eye, Pin, PinOff, Scissors } from 'lucide-react';

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

export default function ContextTracePanel({ trace }) {
    const [open, setOpen] = useState(false);
    const [showAll, setShowAll] = useState(false);

    if (!trace || typeof trace !== 'object') return null;

    const turns = Array.isArray(trace.turns) ? trace.turns : [];
    const sections = Array.isArray(trace.sections) ? trace.sections : [];
    const budgets = trace.budgets && typeof trace.budgets === 'object' ? trace.budgets : {};
    const speakers = trace.speakers || {};
    const config = trace.config || {};
    const dropped = Array.isArray(trace.dropped) ? trace.dropped : [];
    const visible = showAll ? turns : turns.slice(-12);
    const hidden = turns.length - visible.length;

    return (
        <div className="mt-1 rounded-xl border border-white/10 bg-gray-900/40 overflow-hidden">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-colors"
                aria-expanded={open}
            >
                <ChevronRight size={12} className={open ? 'rotate-90 transition-transform' : 'transition-transform'} />
                <Eye size={11} />
                <span className="font-medium text-gray-400">What this reply was told</span>
                <span className="text-gray-500 text-3xs font-mono hidden sm:inline">(Context Inspector)</span>
                <span className="ml-auto text-gray-600 font-mono text-3xs">
                    {turns.length} turn{turns.length === 1 ? '' : 's'} · {sections.length} sections
                    {trace.truncated ? ' · truncated' : ''}
                </span>
            </button>

            {open && (
                <div className="border-t border-white/10 px-3 py-2.5 flex flex-col gap-3 text-xs">
                    <p className="text-gray-400 text-3xs leading-relaxed bg-black/20 p-2 rounded-lg border border-white/5">
                        💡 <strong>Prompt Context Inspector:</strong> The snapshot of dialogue history and system lore that was assembled and sent to the AI model to generate this reply.
                    </p>

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
