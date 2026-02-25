import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import CollapsibleSection from './CollapsibleSection';

describe('CollapsibleSection', () => {
    it('renders title and icon', () => {
        render(
            <CollapsibleSection title="Test Section" icon={<span data-testid="icon">icon</span>}>
                <p>Content</p>
            </CollapsibleSection>
        );

        expect(screen.getByText('Test Section')).toBeInTheDocument();
        expect(screen.getByTestId('icon')).toBeInTheDocument();
    });

    it('renders content by default (defaultOpen=true)', () => {
        render(
            <CollapsibleSection title="Test Section" defaultOpen={true}>
                <p>Visible Content</p>
            </CollapsibleSection>
        );

        expect(screen.getByText('Visible Content')).toBeVisible();
    });

    it('hides content initially when defaultOpen=false', () => {
        render(
            <CollapsibleSection title="Test Section" defaultOpen={false}>
                <p>Hidden Content</p>
            </CollapsibleSection>
        );

        expect(screen.queryByText('Hidden Content')).not.toBeInTheDocument();
    });

    it('toggles content visibility on click', async () => {
        render(
            <CollapsibleSection title="Test Section" defaultOpen={false}>
                <p>Content</p>
            </CollapsibleSection>
        );

        const button = screen.getByRole('button', { name: /Test Section/i });

        // Initial state
        expect(button).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByText('Content')).not.toBeInTheDocument();

        // Click to open
        fireEvent.click(button);

        await waitFor(() => {
            expect(screen.getByText('Content')).toBeVisible();
        });
        expect(button).toHaveAttribute('aria-expanded', 'true');

        // Click to close
        fireEvent.click(button);

        await waitFor(() => {
             expect(screen.queryByText('Content')).not.toBeInTheDocument();
        });
        expect(button).toHaveAttribute('aria-expanded', 'false');
    });

    it('has correct ARIA attributes', () => {
        render(
            <CollapsibleSection title="Test Section" defaultOpen={true}>
                <p>Content</p>
            </CollapsibleSection>
        );

        const button = screen.getByRole('button', { name: /Test Section/i });
        const region = screen.getByRole('region');

        expect(button).toHaveAttribute('aria-controls', region.id);
        expect(region).toHaveAttribute('aria-labelledby', button.id);
    });
});
