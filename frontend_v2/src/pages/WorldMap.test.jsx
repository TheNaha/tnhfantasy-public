import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WorldMap from './WorldMap';

const mockMutateAsync = vi.fn();
const mockRefetch = vi.fn();

vi.mock('../hooks/useLocations', () => ({
    useLocations: () => ({
        data: [
            {
                id: 'loc-1',
                name: 'The Citadel',
                description: 'Ancient fortress',
                map_x: 0.5,
                map_y: 0.5,
                world_id: 'world-1',
            },
        ],
        isLoading: false,
        isError: false,
        refetch: mockRefetch,
    }),
    useUpdateLocation: () => ({
        mutateAsync: mockMutateAsync,
    }),
}));

vi.mock('../hooks/useWorlds', () => ({
    useWorlds: () => ({
        data: [{ id: 'world-1', name: 'Fantasy Realm' }],
        isLoading: false,
        isError: false,
    }),
}));

vi.mock('../api/client', () => ({
    api: { post: vi.fn(), delete: vi.fn() },
}));

describe('WorldMap', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('renders the map and existing location pins', () => {
        render(<WorldMap worldId="world-1" />);
        expect(screen.getByText('The Citadel')).toBeInTheDocument();
    });

    it('opens location editor on svg click with normalized coordinates', () => {
        const { container } = render(<WorldMap worldId="world-1" />);
        const mapSvg = container.querySelector('svg[width="1200"]');

        vi.spyOn(mapSvg, 'getBoundingClientRect').mockReturnValue({
            left: 100,
            top: 50,
            width: 1200,
            height: 800,
        });

        // Click in the middle of the SVG: clientX = 700 (left 100 + 600px = halfway across 1200)
        // clientY = 450 (top 50 + 400px = halfway down 800)
        fireEvent.click(mapSvg, {
            clientX: 700,
            clientY: 450,
        });

        expect(screen.getByText('New Location')).toBeInTheDocument();
        const inputs = screen.getAllByRole('spinbutton');
        // map_x should be 0.5 and map_y should be 0.5
        expect(Number(inputs[0].value)).toBeCloseTo(0.5);
        expect(Number(inputs[1].value)).toBeCloseTo(0.5);
    });

    it('updates position correctly on pin drag end without double-untransform', async () => {
        const { container } = render(<WorldMap worldId="world-1" />);
        const mapSvg = container.querySelector('svg[width="1200"]');
        vi.spyOn(mapSvg, 'getBoundingClientRect').mockReturnValue({
            left: 0,
            top: 0,
            width: 1200,
            height: 800,
        });

        const pinGroup = screen.getByText('The Citadel').closest('g');

        // Start drag
        fireEvent.mouseDown(pinGroup);

        // End drag at 900px, 600px -> normalized: 900/1200 = 0.75, 600/800 = 0.75
        fireEvent.mouseUp(pinGroup, {
            clientX: 900,
            clientY: 600,
        });

        expect(mockMutateAsync).toHaveBeenCalledWith(
            expect.objectContaining({
                id: 'loc-1',
                map_x: 0.75,
                map_y: 0.75,
            })
        );
    });
});
