import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import CardSourceInspector from './CardSourceInspector';
import ScenariosMappingTab from './ScenariosMappingTab';
import StatekeeperTurn0Tab from './StatekeeperTurn0Tab';

describe('CardSourceInspector', () => {
    const mockCard = {
        name: 'Pyrene Blacksmith',
        card_spec: 'chara_card_v3',
        card_spec_version: '3.0',
        creator: 'LoreMaster',
        description: 'Master dwarf blacksmith.',
        personality: 'Boisterous and honest.',
        scenario: 'At the forge.',
        first_mes: 'Welcome to the Pointed Anvil Forge!',
        alternate_greetings: [
            'Outside in the heavy rain, Pyrene greets you.',
            'In the guild hall, Pyrene inspects the blade.',
        ],
        character_book: {
            name: 'Forge Lore',
            entries: [{ keys: ['mithril'], content: 'Rare elven metal' }],
        },
    };

    it('renders character name and card spec badge', () => {
        render(<CardSourceInspector sourceCard={mockCard} />);
        expect(screen.getByText('Pyrene Blacksmith')).toBeInTheDocument();
        expect(screen.getByText(/chara_card_v3/i)).toBeInTheDocument();
        expect(screen.getByText(/LoreMaster/i)).toBeInTheDocument();
    });

    it('displays alternate greetings count badge and accordion', () => {
        render(<CardSourceInspector sourceCard={mockCard} />);
        expect(screen.getByText(/Alternate Greetings \(2\)/i)).toBeInTheDocument();
    });
});

describe('ScenariosMappingTab', () => {
    const mockScenarios = [
        {
            id: 'scenario_0',
            title: 'At The Pointed Anvil',
            description: 'Canonical opening.',
            first_mes: 'Welcome to the forge!',
            location_name: 'The Pointed Anvil',
            story_time: 'Midday',
            is_primary: true,
            selected: true,
        },
        {
            id: 'scenario_1',
            title: 'Guild Hall Meeting',
            description: 'Alternate greeting.',
            first_mes: 'Pyrene looks up from the blueprints.',
            location_name: 'Guild Hall',
            story_time: 'Evening',
            is_primary: false,
            selected: true,
        },
    ];

    it('renders all scenarios with titles and location info', () => {
        const onChange = vi.fn();
        render(<ScenariosMappingTab scenarios={mockScenarios} onChangeScenarios={onChange} />);
        expect(screen.getByText('At The Pointed Anvil')).toBeInTheDocument();
        expect(screen.getByText('Guild Hall Meeting')).toBeInTheDocument();
        expect(screen.getByText('Default Opening')).toBeInTheDocument();
    });

    it('allows changing primary default opening scenario', () => {
        const onChange = vi.fn();
        render(<ScenariosMappingTab scenarios={mockScenarios} onChangeScenarios={onChange} />);
        const setButtons = screen.getAllByRole('button', { name: /Set as Default/i });
        expect(setButtons.length).toBeGreaterThan(0);
        fireEvent.click(setButtons[0]);
        expect(onChange).toHaveBeenCalled();
    });
});

describe('StatekeeperTurn0Tab', () => {
    const mockSnapshot = {
        character_mood: 'Vigilant',
        current_activity: 'Sharpening blade',
        character_outfit: 'Dwarven Leather Apron',
        scene_tension: 3.5,
        relationship_status: 'Cautious respect',
        character_skills: ['Smithing', 'Endurance'],
        user_skills: ['Diplomacy'],
        inventory: ['Hammer'],
    };

    it('renders director controls and lock toggles', () => {
        const onChangeSnapshot = vi.fn();
        const onToggleLock = vi.fn();
        render(
            <StatekeeperTurn0Tab
                snapshot={mockSnapshot}
                lockedFields={['scene_tension', 'character_mood']}
                onChangeSnapshot={onChangeSnapshot}
                onToggleLock={onToggleLock}
            />
        );

        expect(screen.getByText(/3.5 \/ 5.0/i)).toBeInTheDocument();
        expect(screen.getByDisplayValue('Vigilant')).toBeInTheDocument();
        expect(screen.getByText('2 locked')).toBeInTheDocument();

        const lockButtons = screen.getAllByRole('button', { name: /^Locked$/ });
        expect(lockButtons.length).toBe(2);
    });

    it('fires onToggleLock when lock button clicked', () => {
        const onToggleLock = vi.fn();
        render(
            <StatekeeperTurn0Tab
                snapshot={mockSnapshot}
                lockedFields={['character_mood']}
                onChangeSnapshot={vi.fn()}
                onToggleLock={onToggleLock}
            />
        );

        const lockBtn = screen.getByRole('button', { name: /^Locked$/ });
        fireEvent.click(lockBtn);
        expect(onToggleLock).toHaveBeenCalledWith('character_mood');
    });
});
