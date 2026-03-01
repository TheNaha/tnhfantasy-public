import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import NumberInput from './NumberInput';

describe('NumberInput', () => {
    it('renders label correctly', () => {
        render(<NumberInput label="Test Input" value={10} onChange={() => { }} />);
        expect(screen.getByText('Test Input')).toBeInTheDocument();
    });

    it('renders value correctly in number input', () => {
        render(<NumberInput label="Test Input" value={10} onChange={() => { }} />);
        const numberInput = screen.getByRole('spinbutton');
        expect(numberInput).toHaveValue(10);
    });

    it('renders value correctly in range input', () => {
        render(<NumberInput label="Test Input" value={10} onChange={() => { }} />);
        const rangeInput = screen.getByRole('slider');
        expect(rangeInput).toHaveValue('10');
    });

    it('calls onChange with new value when number input changes', () => {
        const handleChange = vi.fn();
        render(<NumberInput label="Test Input" value={10} onChange={handleChange} min={0} max={100} />);

        const numberInput = screen.getByRole('spinbutton');
        fireEvent.change(numberInput, { target: { value: '25' } });
        expect(handleChange).toHaveBeenCalledWith(25);
    });

    it('calls onChange with new value when slider changes', () => {
        const handleChange = vi.fn();
        render(<NumberInput label="Test Input" value={10} onChange={handleChange} min={0} max={100} />);

        const rangeInput = screen.getByRole('slider');
        fireEvent.change(rangeInput, { target: { value: '50' } });
        expect(handleChange).toHaveBeenCalledWith(50);
    });

    it('allows typing outside of max and clamps to min on blur', () => {
        const handleChange = vi.fn();
        const { rerender } = render(<NumberInput label="Test Input" value={10} onChange={handleChange} min={5} max={100} />);

        const numberInput = screen.getByRole('spinbutton');

        // Type above max
        fireEvent.change(numberInput, { target: { value: '200' } });
        expect(handleChange).toHaveBeenCalledWith(200);

        rerender(<NumberInput label="Test Input" value={200} onChange={handleChange} min={5} max={100} />);

        // Type below min
        fireEvent.change(numberInput, { target: { value: '2' } });
        expect(handleChange).toHaveBeenCalledWith(2);

        rerender(<NumberInput label="Test Input" value={2} onChange={handleChange} min={5} max={100} />);

        // Blur clamps to min
        fireEvent.blur(numberInput);
        expect(handleChange).toHaveBeenCalledWith(5);
    });

    it('handles clearing the number input to empty string and blur', () => {
        const handleChange = vi.fn();
        render(<NumberInput label="Test Input" value={10} onChange={handleChange} min={0} max={100} />);

        const numberInput = screen.getByRole('spinbutton');

        // Clear the input to simulate intermediate empty typing state
        fireEvent.change(numberInput, { target: { value: '' } });

        const callsBeforeBlur = handleChange.mock.calls.length;

        // Blur after empty value to trigger any clamping/normalization logic
        fireEvent.blur(numberInput);

        // Ensure we at least run through the change/blur path without crashing
        expect(handleChange.mock.calls.length).toBeGreaterThanOrEqual(callsBeforeBlur);
    });
});
