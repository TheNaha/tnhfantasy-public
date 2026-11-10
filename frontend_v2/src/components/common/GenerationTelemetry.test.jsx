import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import GenerationTelemetry from './GenerationTelemetry';

describe('GenerationTelemetry', () => {
    const mockTimings = {
        queue_seconds: 5.2,
        model_load_seconds: 3.1,
        sampling_seconds: 15.0,
        transfer_seconds: 2.5,
        transfer_bytes: 512000,
        transfer_format: 'webp',
        processing_seconds: 0.5,
        total_backend_seconds: 26.3,
    };

    it('returns null when timings is not provided', () => {
        const { container } = render(<GenerationTelemetry timings={null} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('renders all stage timings and total duration', () => {
        render(<GenerationTelemetry timings={mockTimings} />);

        expect(screen.getByTestId('generation-telemetry')).toBeInTheDocument();
        expect(screen.getAllByText('26.30s').length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText('5.20s')).toBeInTheDocument();
        expect(screen.getByText('3.10s')).toBeInTheDocument();
        expect(screen.getByText('15.00s')).toBeInTheDocument();
        expect(screen.getByText('2.50s')).toBeInTheDocument();
        expect(screen.getByText('0.50s')).toBeInTheDocument();
    });

    it('renders sampling speed when steps is provided', () => {
        render(<GenerationTelemetry timings={mockTimings} steps={30} />);

        // 30 steps / 15.0s = 2.00 it/s
        expect(screen.getByText('2.00 it/s')).toBeInTheDocument();
        expect(screen.getByText(/30 steps @ 2.00 it\/s/)).toBeInTheDocument();
    });

    it('renders transfer size, format and transfer rate', () => {
        render(<GenerationTelemetry timings={mockTimings} />);

        // 512,000 bytes = 500.0 KB (WEBP)
        expect(screen.getByText(/500\.0 KB \(WEBP\)/)).toBeInTheDocument();
        // 512,000 / 2.5s = 200.0 KB/s
        expect(screen.getByText(/200\.0 KB\/s/)).toBeInTheDocument();
    });

    it('renders provider badge when providerId is provided', () => {
        render(<GenerationTelemetry timings={mockTimings} providerId="colab-one" />);

        expect(screen.getByText('colab-one')).toBeInTheDocument();
    });

    it('collapses and expands when collapsible is true', () => {
        render(<GenerationTelemetry timings={mockTimings} collapsible={true} defaultExpanded={false} />);

        expect(screen.queryByText('Queue:')).not.toBeInTheDocument();

        // Click to expand
        fireEvent.click(screen.getByText('Generation Telemetry'));
        expect(screen.getByText('Queue:')).toBeInTheDocument();
    });
});
