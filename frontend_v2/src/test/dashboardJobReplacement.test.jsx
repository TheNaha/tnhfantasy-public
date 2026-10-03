import { describe, it, expect } from 'vitest';
import { buildDashboardItems } from '../utils/dashboardItems';

/**
 * A completed job must stop being a card and become its image.
 *
 * The dashboard merges two lists into one feed: images from the gallery pages,
 * and jobs from the active-jobs query plus page 1's jobs list. A job that has
 * finished has to be *replaced* by the image it produced, and the replacement is
 * what stops a finished job sitting in the timeline forever as a stale
 * "in progress" card.
 *
 * Two real defects are pinned here, both found by driving the live payloads
 * rather than by reading the merge:
 *
 *  1. `job.outputs[0]` is an OBJECT — `{path, type, filename, subfolder}` — and
 *     the fallback that looks the image up by filename passes it to a Map keyed
 *     by string. It can never match, so a job whose asset lacks `metadata.job_id`
 *     is dropped from the feed entirely rather than replaced.
 *
 *  2. A job that completes while its *stale* row is still in the jobs list is
 *     re-merged with that row's old status, and a non-terminal status renders as
 *     a card. That is the "the job card isn't getting replaced" report.
 */

/** Shaped from a real `/api/jobs?limit=20` response. */
const completedJob = {
    id: 'job-1',
    task_type: 'image',
    status: 'completed',
    created_at: '2026-10-03T10:38:41Z',
    outputs: [
        {
            path: '/data/output/default_user/main/2026/10/03/T2I_2026-10-03_10-38-41_00001_.png',
            type: 'image',
            filename: 'T2I_2026-10-03_10-38-41_00001_.png',
            subfolder: 'default_user/main/2026/10/03',
        },
    ],
};

const FILE = 'T2I_2026-10-03_10-38-41_00001_.png';

const imageWithJobId = {
    name: FILE,
    type: 'image',
    date: '2026-10-03T10:38:41Z',
    mtime: '2026-10-03T10:38:41Z',
    metadata: { job_id: 'job-1' },
};

const page = (files, jobs = []) => ({ files, jobs, nextPage: undefined });

describe('a completed job is replaced by its image', () => {
    it('replaces it when the asset carries metadata.job_id', () => {
        const { items } = buildDashboardItems(
            { pages: [page([imageWithJobId], [completedJob])] },
            [],
        );

        const cards = items.filter((i) => i.type === 'job');
        expect(cards).toHaveLength(0);
        expect(items).toHaveLength(1);
        expect(items[0].type).toBe('image');
        expect(items[0].name).toBe(FILE);
        // The replacement carries the job it replaced, for the detail modal.
        expect(items[0]._replacedJobId).toBe('job-1');
    });

    it('replaces it when the asset has NO job_id, by matching the output filename', () => {
        // The asset indexer does not always stamp job_id — a re-index, an import,
        // an output written outside a job. The filename fallback is what covers
        // that case, and it was dead: `outputs[0]` is an object and
        // `imagesByName` is keyed by string, so the lookup returned undefined and
        // the job was silently dropped from the feed.
        const { items } = buildDashboardItems(
            { pages: [page([{ ...imageWithJobId, metadata: {} }], [completedJob])] },
            [],
        );

        expect(items.filter((i) => i.type === 'job')).toHaveLength(0);
        expect(items).toHaveLength(1);
        expect(items[0].type).toBe('image');
        expect(items[0].name).toBe(FILE);
        // Not just "an image showed up" — the image must be the *replacement*, so
        // it keeps the link to the job that made it. The image also renders via
        // the unmatched-files pass below, so without this assertion this test
        // passes for the wrong reason: the fallback is dead and the pass covers for
        // it, which is how it stayed dead.
        expect(items[0]._replacedJobId).toBe('job-1');
    });

    it('keeps a running job as a card', () => {
        // A genuinely different job, and the image belongs to the completed one.
        // An asset stamped `job_id: job-1` IS evidence that job-1 finished, so a
        // "running" job carrying its own output is a contradiction the merge is
        // right to resolve in favour of the asset.
        const running = { ...completedJob, id: 'job-2', status: 'processing', outputs: [] };
        const { items } = buildDashboardItems(
            { pages: [page([imageWithJobId], [])] },
            [running],
        );

        expect(items.filter((i) => i.type === 'job')).toHaveLength(1);
        expect(items.filter((i) => i.type === 'job')[0].id).toBe('job-2');
    });

    it('an asset stamped with a job id beats a stale non-terminal status', () => {
        // The rule the fix turns on, stated directly: the asset index is the
        // ground truth. A job whose output is sitting in the library has finished,
        // whatever the row still claims.
        const staleRunning = { ...completedJob, status: 'processing', outputs: [] };
        const { items } = buildDashboardItems(
            { pages: [page([imageWithJobId], [staleRunning])] },
            [],
        );

        expect(items.filter((i) => i.type === 'job')).toHaveLength(0);
        expect(items).toHaveLength(1);
        expect(items[0]._replacedJobId).toBe('job-1');
    });

    it('does not render a completed job as a card when its image has not landed yet', () => {
        // Between "the job completed" and "the asset row is queryable" there is a
        // window. The job must vanish from the feed in it, not linger as a card
        // showing a finished job as if it were still running — which is what the
        // stale-row merge below produces.
        const { items } = buildDashboardItems(
            { pages: [page([], [completedJob])] },
            [],
        );
        expect(items.filter((i) => i.type === 'job')).toHaveLength(0);
    });

    it('a stale jobs-list row cannot resurrect a finished job as a card', () => {
        // What the dashboard actually held at the moment of the bug report: the
        // completion event removed the job from `['jobs','active']`, but the
        // jobs list fetched with page 1 still described it as `processing`. The
        // merge takes the active list as authoritative only for ids it *has*, so
        // a stale historical row survives — and a non-terminal status renders as a
        // card.
        const staleRow = { ...completedJob, status: 'processing', outputs: [] };
        const { items } = buildDashboardItems(
            { pages: [page([imageWithJobId], [staleRow])] },
            [],
        );

        expect(items.filter((i) => i.type === 'job')).toHaveLength(0);
        expect(items.filter((i) => i.type === 'image')).toHaveLength(1);
    });
});