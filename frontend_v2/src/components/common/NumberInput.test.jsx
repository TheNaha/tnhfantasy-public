import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import NumberInput from './NumberInput';

describe('NumberInput', () => {
    it('renders label correctly', () => {
        render(<NumberInput label="Test Input" value={10} onChange={() => {}} min={0} max={100} />);
        expect(screen.getByText('Test Input')).toBeInTheDocument();
    });

    it('renders value correctly', () => {
        render(<NumberInput label="Test Input" value={10} onChange={() => {}} min={0} max={100} />);
        expect(screen.getByRole('spinbutton')).toHaveValue(10);
    });

    it('calls onChange with decremented value when - button clicked', () => {
        const handleChange = vi.fn();
        render(<NumberInput label="Test Input" value={10} onChange={handleChange} min={0} max={100} step={1} />);

        fireEvent.click(screen.getByLabelText('Decrease Test Input'));
        expect(handleChange).toHaveBeenCalledWith(9);
    });

    it('calls onChange with incremented value when + button clicked', () => {
        const handleChange = vi.fn();
        render(<NumberInput label="Test Input" value={10} onChange={handleChange} min={0} max={100} step={1} />);

        fireEvent.click(screen.getByLabelText('Increase Test Input'));
        expect(handleChange).toHaveBeenCalledWith(11);
    });

    it('does not decrement below min', () => {
        const handleChange = vi.fn();
        render(<NumberInput label="Test Input" value={0} onChange={handleChange} min={0} max={100} step={1} />);

        const button = screen.getByLabelText('Decrease Test Input');
        expect(button).toBeDisabled();

        fireEvent.click(button);
        expect(handleChange).not.toHaveBeenCalled();
    });

    it('does not increment above max', () => {
        const handleChange = vi.fn();
        render(<NumberInput label="Test Input" value={100} onChange={handleChange} min={0} max={100} step={1} />);

        const button = screen.getByLabelText('Increase Test Input');
        expect(button).toBeDisabled();

        fireEvent.click(button);
        expect(handleChange).not.toHaveBeenCalled();
    });
});
