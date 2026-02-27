import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import SettingsPanel from './SettingsPanel';

// Mock dependencies
vi.mock('../../store/generatorStore', () => ({
    useGeneratorStore: vi.fn(() => ({
        // Mock store values
        width: 512,
        height: 512,
        batchSize: 1,
        seed: 12345,
        steps: 20,
        cfg: 7.0,
        sampler: 'euler_ancestral',
        scheduler: 'normal',
        aspectRatioLocked: false,

        // Mock setters
        setWidth: vi.fn(),
        setHeight: vi.fn(),
        setBatchSize: vi.fn(),
        setSeed: vi.fn(),
        setSteps: vi.fn(),
        setCfg: vi.fn(),
        setSampler: vi.fn(),
        setScheduler: vi.fn(),
        setAspectRatioLocked: vi.fn(),

        // Enhancements
        hiresFix: false,
        hiresUpscaler: 'Latent',
        hiresDenoise: 0.5,
        hiresUpscale: 2.0,
        hiresSteps: 15,
        setHiresFix: vi.fn(),
        setHiresUpscaler: vi.fn(),
        setHiresDenoise: vi.fn(),
        setHiresUpscale: vi.fn(),
        setHiresSteps: vi.fn(),

        adetailer: false,
        adetailerModel: 'face_yolov8n.pt',
        adetailerPrompt: '',
        adetailerNegative: '',
        adetailerSteps: 20,
        adetailerDenoise: 0.4,
        adetailerInpaintMasked: true,
        setAdetailer: vi.fn(),
        setAdetailerModel: vi.fn(),
        setAdetailerPrompt: vi.fn(),
        setAdetailerNegative: vi.fn(),
        setAdetailerSteps: vi.fn(),
        setAdetailerDenoise: vi.fn(),
        setAdetailerInpaintMasked: vi.fn()
    }))
}));

describe('SettingsPanel', () => {
    const mockUpscalerModels = [{ name: 'R-ESRGAN 4x+' }, { name: 'SwinIR 4x' }];
    const mockAdetailerModels = [{ name: 'face_yolov8n.pt' }, { name: 'hand_yolov8n.pt' }];

    it('renders basic settings correctly', () => {
        render(
            <SettingsPanel
                upscalerModels={mockUpscalerModels}
                adetailerModels={mockAdetailerModels}
            />
        );

        // Check for section headers
        expect(screen.getByText(/Generation Settings/i)).toBeInTheDocument();
        expect(screen.getByText(/Enhancements/i)).toBeInTheDocument();

        // Check for text labels
        expect(screen.getByText(/Resolution/i)).toBeInTheDocument();

        // Check for inputs by value since labels aren't strictly associated yet
        const inputs = screen.getAllByDisplayValue('512');
        expect(inputs.length).toBeGreaterThan(0);
    });

    it('renders enhancement settings', () => {
        render(
            <SettingsPanel
                upscalerModels={mockUpscalerModels}
                adetailerModels={mockAdetailerModels}
            />
        );

        expect(screen.getByText(/Hi-Res Fix/i)).toBeInTheDocument();
        expect(screen.getByText(/ADetailer/i)).toBeInTheDocument();
    });

    it('has accessible inputs', () => {
        render(
            <SettingsPanel
                upscalerModels={mockUpscalerModels}
                adetailerModels={mockAdetailerModels}
            />
        );

        // Check resolution inputs via aria-label
        expect(screen.getByLabelText('Width')).toBeInTheDocument();
        expect(screen.getByLabelText('Height')).toBeInTheDocument();

        // Check other inputs via associated labels

        // Batch Size
        expect(screen.getByLabelText('Batch Size', { selector: 'input' })).toBeInTheDocument();

        expect(screen.getByLabelText('Seed', { selector: 'input' })).toBeInTheDocument();

        // Steps appears multiple times (Main, Hi-Res, ADetailer), so we expect multiple
        const stepsInputs = screen.getAllByLabelText('Steps', { selector: 'input' });
        expect(stepsInputs.length).toBeGreaterThanOrEqual(1);

        expect(screen.getByLabelText('CFG Scale', { selector: 'input' })).toBeInTheDocument();
        expect(screen.getByLabelText('Sampler', { selector: 'select' })).toBeInTheDocument();
        expect(screen.getByLabelText('Scheduler', { selector: 'select' })).toBeInTheDocument();

        // Check buttons
        expect(screen.getByLabelText(/Lock Aspect Ratio/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/Randomize Seed/i)).toBeInTheDocument();
    });
});
