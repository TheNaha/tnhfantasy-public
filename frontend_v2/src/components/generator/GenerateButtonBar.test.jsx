import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import GenerateButtonBar from './GenerateButtonBar';

/**
 * A prompt is not enough to run a job.
 *
 * Found by driving the real UI on a phone and submitting: the built workflow
 * carried `ckpt_name: ""`, and the job failed ~40 seconds later with "All
 * providers failed: modal-zetsuke" — an error naming the provider for something
 * the client sent. Fifteen checkpoints were installed; `selectedCheckpoint` is
 * `null` in the store until you pick one, and nothing picks one for you.
 *
 * On a phone this is likelier than on desktop, because the model picker sits
 * well below the fold of a form that is 3.3 screens long.
 *
 * `InpaintGenerator` already guards this with its own `canGenerate`; this route
 * did not, and the button was `disabled={generating || !prompt}`.
 */
function Harness({ blockingReason = null, prompt = 'a lighthouse' }) {
    const [generating] = useState(false);
    return (
        <GenerateButtonBar
            generating={generating}
            progress={null}
            prompt={prompt}
            blockingReason={blockingReason}
            onGenerate={vi.fn()}
            onQueue={vi.fn()}
            onGenerateVariations={vi.fn()}
        />
    );
}

/**
 * The primary submit button. Selected by DOM position — it is the last child of
 * the bar — because every button here shares the same disabled reason, so a
 * name or title query cannot tell them apart. That is deliberate: all three
 * must carry the reason.
 */
const allButtons = () => screen.getAllByRole('button');
const generateButton = () => allButtons().at(-1);

describe('GenerateButtonBar — a missing checkpoint blocks submission', () => {
    it('is disabled and says so when no model is selected', () => {
        render(<Harness blockingReason="Select a checkpoint first" />);
        const btn = generateButton();
        expect(btn).toBeDisabled();
        expect(btn).toHaveAttribute('title', 'Select a checkpoint first');
        // The label carries the reason, not just an inert "Generate".
        expect(btn.textContent).toMatch(/select a checkpoint/i);
    });

    it('is enabled once a model is selected', () => {
        render(<Harness blockingReason={null} />);
        expect(generateButton()).toBeEnabled();
        expect(generateButton().textContent).toMatch(/^\s*Generate\s*$/);
    });

    it('is disabled with no prompt either', () => {
        render(<Harness blockingReason={null} prompt="" />);
        expect(generateButton()).toBeDisabled();
    });

    it('blocks the queue and variations buttons too, not just Generate', () => {
        render(<Harness blockingReason="Select a checkpoint first" />);
        // Same failure mode, three entry points.
        for (const btn of allButtons()) {
            expect(btn).toBeDisabled();
        }
    });

    it('names the missing prerequisite rather than failing later', () => {
        render(<Harness blockingReason="Select a checkpoint first" />);
        // Every button's tooltip has to carry the reason — on a phone there is
        // no hover, so a tooltip is the only place it can live besides the label.
        const titles = allButtons().map((b) => b.getAttribute('title'));
        expect(titles.every((t) => t === 'Select a checkpoint first')).toBe(true);
    });
});
