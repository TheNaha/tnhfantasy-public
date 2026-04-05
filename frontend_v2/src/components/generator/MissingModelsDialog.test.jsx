import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const navigateMock = vi.fn();

vi.mock('react-router-dom', () => ({
    useNavigate: () => navigateMock,
}));

import MissingModelsDialog from './MissingModelsDialog';

describe('MissingModelsDialog', () => {
    beforeEach(() => {
        navigateMock.mockReset();
    });

    it('navigates to the model manager route with browser navigation', () => {
        const onClose = vi.fn();

        render(
            <MissingModelsDialog
                isOpen
                onClose={onClose}
                validationResult={{
                    global_missing: {
                        checkpoints: ['missing-model.safetensors'],
                    },
                    missing_models: {},
                    required_models: {
                        checkpoints: ['missing-model.safetensors'],
                    },
                }}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: /open model manager/i }));

        expect(onClose).toHaveBeenCalledTimes(1);
        expect(navigateMock).toHaveBeenCalledWith('/models');
    });

    it('prefers the supplied model manager callback when provided', () => {
        const onClose = vi.fn();
        const onOpenModelManager = vi.fn();

        render(
            <MissingModelsDialog
                isOpen
                onClose={onClose}
                onOpenModelManager={onOpenModelManager}
                validationResult={{
                    global_missing: {
                        checkpoints: ['missing-model.safetensors'],
                    },
                    missing_models: {},
                    required_models: {},
                }}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: /open model manager/i }));

        expect(onClose).toHaveBeenCalledTimes(1);
        expect(onOpenModelManager).toHaveBeenCalledTimes(1);
        expect(navigateMock).not.toHaveBeenCalled();
    });
});
