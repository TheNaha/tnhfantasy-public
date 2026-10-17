import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import React from 'react';

import ContextTracePanel from './ContextTracePanel';

/**
 * What a reply was actually told, shown to the user.
 *
 * Until this existed the only introspection was `SystemPromptPanel`, which shows
 * the SYSTEM prompt and where each section came from — and nothing about the
 * conversation. Which turns were sent, which were labelled as narration, which
 * was pruned to fit the budget: all invisible. A reply that ignored something
 * three turns ago was indistinguishable from one whose text had been trimmed
 * out entirely, and the group-chat speaker labelling could not be verified
 * without reading the payload.
 */

const TRACE = {
    v: 1,
    config: { label_speakers: true, narrator_prefix: '[Narration]', image_prefix: '[Scene]' },
    speakers: { count: 2, named: ['Aria', 'Bram'] },
    sections: [
        { label: 'Character', source: 'character', chars: 1240 },
        { label: 'Lorebook', source: 'lorebook', chars: 320 },
    ],
    turns: [
        // One pinned turn, so the pinned marker is exercised rather than
        // only the prunable one.
        { role: 'user', label: null, kind: 'user', pinned: true, chars: 42 },
        { role: 'assistant', label: 'Bram: The door is barred.', kind: 'char', pinned: false, chars: 24 },
        { role: 'assistant', label: '[Narration] Rain began.', kind: 'narrator', pinned: false, chars: 14 },
        { role: 'system', label: null, kind: null, pinned: false, chars: 30 },
    ],
    dropped: [],
    budgets: { generate_image: { spent: 1, max: 3 }, narrate_scene: { spent: 0, max: 1 } },
    budget_tokens: 4096,
    system_prompt_chars: 2180,
    truncated: false,
};

function open() {
    render(<ContextTracePanel trace={TRACE} />);
    fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));
}

describe('ContextTracePanel', () => {
    it('renders nothing without a trace', () => {
        const { container } = render(<ContextTracePanel trace={null} />);
        expect(container.firstChild).toBeNull();
    });

    it('is collapsed by default and opens on click', () => {
        render(<ContextTracePanel trace={TRACE} />);
        expect(screen.queryByText(/Turns sent/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));
        expect(screen.getByText(/Turns sent/)).toBeInTheDocument();
    });

    it('shows the turn count and section count in the header', () => {
        render(<ContextTracePanel trace={TRACE} />);
        expect(screen.getByText('4 turns · 2 sections')).toBeInTheDocument();
    });

    it('shows every turn with its role, size and prunability', () => {
        open();
        expect(screen.getByText('You')).toBeInTheDocument();
        expect(screen.getAllByText('Assistant').length).toBe(2);
        expect(screen.getByText('System')).toBeInTheDocument();
        // The preview is what makes a digest readable: which turn was the
        // narration, and which one was Bram.
        expect(screen.getByText(/Bram: The door is barred\./)).toBeInTheDocument();
        expect(screen.getByText(/\[Narration\] Rain began\./)).toBeInTheDocument();
        expect(screen.getByText('42c')).toBeInTheDocument();
        // One of the four is pinned, so three are prunable.
        expect(screen.getAllByLabelText('prunable').length).toBe(3);
        expect(screen.getByLabelText('pinned')).toBeInTheDocument();
    });

    it('shows the narration marker the mapping actually applied', () => {
        open();
        // The label is configured, not hardcoded, so the panel must show what
        // was used — that is the whole property a user cannot otherwise check.
        expect(screen.getByText('narration marker:')).toBeInTheDocument();
        expect(screen.getByText('[Narration]')).toBeInTheDocument();
    });

    it('names the speakers so a group chat is verifiable', () => {
        open();
        expect(screen.getByText('speakers:')).toBeInTheDocument();
        expect(screen.getByText('2 (Aria, Bram)')).toBeInTheDocument();
        expect(screen.getByText('names on')).toBeInTheDocument();
    });

    it('shows the costed-tool budgets with spent and max', () => {
        open();
        // Two of these, and the point of showing them is that a refused tool is
        // otherwise indistinguishable from a model that simply chose not to.
        expect(screen.getByText('generate_image:')).toBeInTheDocument();
        expect(screen.getByText('1/3')).toBeInTheDocument();
        expect(screen.getByText('narrate_scene:')).toBeInTheDocument();
        expect(screen.getByText('0/1')).toBeInTheDocument();
    });

    it('shows the prompt sections with their sizes', () => {
        open();
        expect(screen.getByText('Character')).toBeInTheDocument();
        expect(screen.getByText('Lorebook')).toBeInTheDocument();
        expect(screen.getByTitle('character · 1240 characters')).toBeInTheDocument();
        expect(screen.getByText(/system prompt 2180c · budget 4096 tok/)).toBeInTheDocument();
    });

    it('surfaces messages that did not become turns', () => {
        render(<ContextTracePanel trace={{ ...TRACE, dropped: ['world_state', 'unknown'] }} />);
        fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));
        expect(screen.getByText(/2 stored messages did not become turns/)).toBeInTheDocument();
        expect(screen.getByText(/\(not world-state\)/)).toBeInTheDocument();
    });

    it('says so when the trace is truncated rather than looking complete', () => {
        render(<ContextTracePanel trace={{ ...TRACE, truncated: true }} />);
        expect(screen.getByText(/truncated/)).toBeInTheDocument();
    });

    it('collapses older turns behind a control', () => {
        const many = { ...TRACE, turns: TRACE.turns.concat(TRACE.turns, TRACE.turns, TRACE.turns) };
        render(<ContextTracePanel trace={many} />);
        fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));
        const reveal = screen.getByRole('button', { name: /show 4 earlier turns/ });
        fireEvent.click(reveal);
        // Revealing is one-way, so the button is gone — and 16 turns are now
        // rendered rather than the last 12.
        expect(screen.queryByRole('button', { name: /show \d+ earlier turns/ })).not.toBeInTheDocument();
        // 16 turns, and the fixture's 4 user turns are all of them now.
        expect(screen.getAllByText('You').length).toBe(4);
    });

    it('marks a truncated trace in the header', () => {
        render(<ContextTracePanel trace={{ ...TRACE, turns: new Array(80).fill(TRACE.turns[0]), truncated: true }} />);
        expect(screen.getByText(/80 turns · 2 sections · truncated/)).toBeInTheDocument();
    });
});

describe('ContextTracePanel execution line', () => {
    // Which provider and model produced the reply. The trace is built at send
    // time and the provider is assigned by the load balancer, so this is stamped
    // at finalize — without it, two replies with the same prompt and different
    // results are indistinguishable on the message.
    it('shows the provider and model a reply ran on', () => {
        render(<ContextTracePanel trace={{ ...TRACE, execution: { provider_id: 'gpu-box-3', model: 'mistral-7b', task_type: 'llm' } }} />);
        fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));
        // The id and the model each sit in their own span, so they are matched
        // directly; the "ran on" prose is a sibling of both.
        expect(screen.getByText('gpu-box-3')).toBeInTheDocument();
        expect(screen.getByText('mistral-7b')).toBeInTheDocument();
        expect(screen.getByText((_t, el) => el?.tagName === 'P' && el?.textContent?.includes('ran on'))).toBeInTheDocument();
        expect(screen.getByText('mistral-7b')).toBeInTheDocument();
    });

    it('says "unassigned" rather than showing a blank when the provider is unknown', () => {
        render(<ContextTracePanel trace={{ ...TRACE, execution: { provider_id: null, model: 'm', task_type: 'llm' } }} />);
        fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));
        expect(screen.getByText('unassigned')).toBeInTheDocument();
    });

    it('omits the line entirely for a trace with no execution block', () => {
        render(<ContextTracePanel trace={TRACE} />);
        fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));
        expect(screen.queryByText((_t, el) => el?.tagName === 'P' && el?.textContent?.includes('ran on'))).not.toBeInTheDocument();
    });

    it('renders the Director Decision Snapshot when director_decision is in the trace', () => {
        const traceWithDecision = {
            ...TRACE,
            director_decision: {
                turn_type: 'dialogue',
                pacing_directive: 'escalate_conflict',
                scene_tension: 3,
                emotional_tone: 'tense',
                character_expression: 'glaring intently',
                fate_check_needed: true,
                fate_outcome: 'success',
                fate_dc: 14,
                suggested_action_chips: ['Defend the entrance', 'Cast counterspell'],
                reasoning_summary: 'Target is aggressive and preparing a lethal strike.'
            }
        };
        render(<ContextTracePanel trace={traceWithDecision} />);
        fireEvent.click(screen.getByRole('button', { name: /what this reply was told/i }));

        expect(screen.getByText('Director Decision Snapshot')).toBeInTheDocument();
        expect(screen.getByText('escalate_conflict')).toBeInTheDocument();
        expect(screen.getByText('Tension 3/5')).toBeInTheDocument();
        expect(screen.getByText('tense')).toBeInTheDocument();
        expect(screen.getByText('glaring intently')).toBeInTheDocument();
        expect(screen.getByText('Defend the entrance')).toBeInTheDocument();
        expect(screen.getByText(/Target is aggressive and preparing a lethal strike/)).toBeInTheDocument();
    });
});
