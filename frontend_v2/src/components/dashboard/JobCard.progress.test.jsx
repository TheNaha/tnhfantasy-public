/**
 * `progress` and `overall_progress` are not interchangeable, and swapping them
 * makes a live job look stalled.
 *
 * The backend computes them differently, in `services/provider_client.py`:
 *
 *   on a ComfyUI `progress` frame:
 *     progress         = the sampler's own percentage   ("Rendering: N%")
 *     overall_progress = nodes done / total nodes
 *
 *   on a `node` frame:
 *     overall_progress = nodes done / total nodes      ("Executing node 3/9...")
 *
 * A checkpoint sampler is ONE node and can run for a minute, so
 * `overall_progress` is frozen for the whole time anything is actually
 * happening, then jumps. Measured over a real 20-step generation: 24 socket
 * events in 40s at a 1.25s median — genuinely live — while the node counter read
 * 0, 58, 83, 83, 83, 100. Sitting at 83% for fifteen seconds is what "the
 * progress is pooled" looked like.
 *
 * The two bars were also labelled the other way round: the node counter was
 * captioned "Workflow" and the sampler percentage "Node".
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import JobCard from './JobCard';

// JobCard calls `useJobStatus`, which is a `useQuery`. Without a client it
// throws before rendering, which reads as a test bug rather than a missing wrapper.
const renderCard = (job) => render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <JobCard job={job} onClick={() => {}} />
    </QueryClientProvider>
);

/** The sampler percentage, falling back to the node counter before sampling starts. */
const shown = (job) => {
    const sampling = job.progress > 0 ? job.progress : (job.overall_progress || 0);
    const nodes = job.overall_progress || 0;
    return { sampling: Math.round(sampling), nodes: Math.round(nodes) };
};

const midRunJob = (over = {}) => ({
    id: 'j1',
    status: 'generating',
    task_type: 'image',
    provider_id: 'modal-hp196',
    workflow: { prompt: { '1': { class_type: 'CheckpointLoaderSimple' } } },
    total_nodes: 3,
    metadata: {},
    ...over,
});

describe('the two progress fields are not interchangeable', () => {
    it('a frozen node counter is not what the user is shown', () => {
        // Sampler at 43%, node counter stuck at 83% — the shape a real run has
        // for most of its duration.
        const job = midRunJob({ progress: 43, overall_progress: 83 });
        const r = shown(job);
        expect(r.sampling).toBe(43);
        expect(r.nodes).toBe(83);
        // The headline is the one that is moving.
        expect(r.sampling).not.toBe(r.nodes);
    });

    it('falls back to the node counter before the sampler reports anything', () => {
        // `progress` is a non-nullable float defaulting to 0, so 0 means "the
        // sampler has not reported yet", not "no progress".
        const r = shown(midRunJob({ progress: 0, overall_progress: 25 }));
        expect(r.sampling).toBe(25);
    });

    it('a missing field reads as zero rather than NaN', () => {
        const r = shown(midRunJob({ progress: undefined, overall_progress: undefined }));
        expect(r.sampling).toBe(0);
        expect(r.nodes).toBe(0);
    });
});

describe('JobCard renders both, labelled for what they measure', () => {
    it('leads with the sampler percentage and names the second bar Nodes', () => {
        renderCard(midRunJob({ progress: 43, overall_progress: 83 }));

        // The prominent bar shows the moving number.
        expect(screen.getByText('43%')).toBeInTheDocument();
        // The coarse one is present but secondary, and named for what it is.
        expect(screen.getByText('83%')).toBeInTheDocument();
        expect(screen.getByText('Nodes')).toBeInTheDocument();
        // Not the old, swapped captions.
        expect(screen.queryByText('Workflow')).not.toBeInTheDocument();
    });

    it('does not show a frozen number as the headline', () => {
        renderCard(midRunJob({ progress: 43, overall_progress: 83 }));
        // The first percentage in the card is the one that moves.
        const percents = screen.getAllByText(/^\d+%$/).map((el) => el.textContent);
        expect(percents[0]).toBe('43%');
    });

    it('hides the node bar until the sampler starts', () => {
        renderCard(midRunJob({ progress: 0, overall_progress: 40 }));
        // Only one bar, captioned Workflow, because nothing is sampling yet.
        expect(screen.getByText('Workflow')).toBeInTheDocument();
        expect(screen.queryByText('Nodes')).not.toBeInTheDocument();
    });
});
