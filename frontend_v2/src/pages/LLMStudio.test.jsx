import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import LLMStudio from './LLMStudio';

// Mock confirmation store
const mockConfirm = vi.fn();
vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: mockConfirm }),
}));

// Mock settingsApi
vi.mock('../api/settingsApi', () => ({
    settingsApi: {
        get: vi.fn().mockResolvedValue({
            settings: {
                ai: {
                    maxContextTokens: 4096,
                    temperature: 0.8,
                    top_p: 1.0,
                    max_output_tokens: 2048,
                    ttsEnabled: true,
                    ragEnabled: true,
                    ragMaxDistance: 0.6,
                }
            }
        }),
        update: vi.fn().mockResolvedValue({ status: 'success' }),
        getSystemPrompts: vi.fn().mockResolvedValue({
            blocks: {
                roleplay_default: 'Default roleplay prompt',
                narrator: 'Default narrator prompt',
                suggest_instruction: 'Default suggest prompt',
            }
        }),
        updateSystemPrompts: vi.fn().mockResolvedValue({ status: 'success' }),
    }
}));

vi.mock('../hooks/useProvidersPageData', () => ({
    default: () => ({
        providers: [
            { id: 'modal_llm', worker_type: 'llm', is_default: true, capabilities: ['llm'] }
        ],
        loading: false,
    }),
}));

const mockEvaluateDirector = vi.fn();

vi.mock('../hooks/useLLMProviderStatus', () => ({
    useLLMProviderStatus: () => ({
        providers: [{ id: 'modal_llm', worker_type: 'llm', is_default: true }],
        enabledProviders: [{ provider_id: 'modal_llm', is_default: true }],
        defaultProvider: { provider_id: 'modal_llm', model_id: 'artemis_31b_q4' },
        availableModels: [{ id: 'artemis_31b_q4', name: 'Artemis 31B' }],
        isLoading: false,
        isHealthy: true,
        isModelsLoading: false,
    }),
    useSetLLMDefault: () => ({
        mutateAsync: vi.fn().mockResolvedValue({}),
        isPending: false,
    }),
    useLLMCatalog: () => ({
        data: {
            active: { rp: 'Artemis 31B', util: 'Gemma 3 12B', decisions: 'laya_english' },
            catalog: {
                'Artemis 31B': { note: 'Roleplay prose engine' },
                'Gemma 3 12B': { note: 'Statekeeper updater' },
                'laya_english': { engine_type: 'system1_laya' },
            },
        },
        isLoading: false,
    }),
    useSetActiveModels: () => ({
        mutate: vi.fn(),
        isPending: false,
    }),
    useEvaluateDirectorDecisions: () => ({
        mutate: mockEvaluateDirector,
        data: {
            provider_tier: 'modal',
            model_id: 'laya_english',
            latency_ms: 42,
            next_speaker: 'character',
            scene_tension: 3,
            scene_tension_label: 'Moderate',
            pacing_directive: 'deepen_intimacy',
            pacing_speed: 2,
            pacing_speed_label: 'standard',
            emotional_tone: 'tender',
            character_expression: 'soft smile',
            image_focus: 'close_up',
            trigger_image_prob: 0.85,
            is_risky_action_probability: 0.15,
            action_difficulty_label: 'easy',
            should_run_updater: true,
            updater_gates: {
                gate_world_state: 0.10,
                gate_character_state: 0.75,
                gate_inventory_or_items: 0.20,
                gate_durable_memory: 0.65,
                gate_lore_discovery: 0.05,
            },
        },
        isPending: false,
    }),
}));

// Mock useWorldVault hooks
const mockAgents = [
    {
        id: 'agent-1',
        name: 'Character Persona',
        slug: 'character',
        agent_type: 'character',
        description: 'Standard character dialogue persona',
        system_prompt_template: 'You are {{character}}.',
        model_target: 'rp',
        is_builtin: true,
        enabled: true,
    },
    {
        id: 'agent-2',
        name: 'Scene Narrator',
        slug: 'narrator',
        agent_type: 'narrator',
        description: 'Atmospheric scene descriptions and world narration',
        system_prompt_template: 'You are the omniscient Narrator.',
        model_target: 'rp',
        is_builtin: true,
        enabled: true,
    },
    {
        id: 'agent-3',
        name: 'Dungeon Master',
        slug: 'dungeon_master',
        agent_type: 'specialist',
        description: 'Enforces tactical combat consequences and rules',
        system_prompt_template: 'You are the Dungeon Master.',
        model_target: 'util',
        is_builtin: false,
        enabled: true,
    },
];

const mockCreateAgent = vi.fn().mockResolvedValue({ id: 'agent-4' });
const mockUpdateAgent = vi.fn().mockResolvedValue({ id: 'agent-3' });
const mockDeleteAgent = vi.fn().mockResolvedValue({});
const mockSimulate = vi.fn().mockResolvedValue({
    triage: {
        next_speaker: 'dungeon_master',
        fate_outcome: 'success_with_cost',
        is_risky_action_probability: 0.72,
    },
    audit: {
        should_run_updater: true,
        active_gate_keys: ['gate_character_mood', 'gate_inventory_or_items'],
        updater_gates: {
            gate_character_mood: 0.82,
            gate_inventory_or_items: 0.75,
            gate_location: 0.25,
            gate_weather: 0.90,
        },
    },
    agent_profile: {
        slug: 'dungeon_master',
        name: 'Dungeon Master',
        variant_slug: 'cinematic',
        rendered_prompt_preview: 'You are the Dungeon Master of the Obsidian Citadel.',
    },
});

vi.mock('../hooks/useWorldVault', () => ({
    useAgents: () => ({
        data: mockAgents,
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
    }),
    // The Agent tab loads the agents and their variants in one request. The
    // fixture carries the same agents, each with its (empty) variant list.
    useAgentsWithVariants: () => ({
        data: mockAgents.map((a) => ({ ...a, variants: [], active_variant_slug: null })),
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
    }),
    getAgentAvatarUrl: (id) => (id ? `http://localhost:8002/api/v2/agents/${id}/avatar` : null),
    useUploadAgentAvatar: () => ({
        mutateAsync: vi.fn().mockResolvedValue({}),
        isPending: false,
    }),
    useCreateAgent: () => ({
        mutateAsync: mockCreateAgent,
        isPending: false,
    }),
    useUpdateAgent: () => ({
        mutateAsync: mockUpdateAgent,
        isPending: false,
    }),
    useDeleteAgent: () => ({
        mutateAsync: mockDeleteAgent,
        isPending: false,
    }),
    useSimulateWorkflow: () => ({
        mutateAsync: mockSimulate,
        isPending: false,
    }),
    useAgentVariants: () => ({
        data: [],
        isLoading: false,
        isError: false,
    }),
    useCreateAgentVariant: () => ({
        mutateAsync: vi.fn(),
        isPending: false,
    }),
    useUpdateAgentVariant: () => ({
        mutateAsync: vi.fn(),
        isPending: false,
    }),
    useDeleteAgentVariant: () => ({
        mutateAsync: vi.fn(),
        isPending: false,
    }),
    useActivateAgentVariant: () => ({
        mutateAsync: vi.fn(),
        isPending: false,
    }),
    useLLMDefaultProvider: () => ({
        data: { active_model: 'Modal / Artemis 31B Q4', util_model: 'Gemma 3 12B Heretic' },
    }),
    useLLMAvailableModels: () => ({
        data: ['Artemis 31B', 'Gemma 3 12B'],
    }),
    useLLMRuntimeDefaults: () => ({
        data: { temperature: 0.7, top_p: 0.9, max_tokens: 1024 },
    }),
    useLLMRouting: () => ({
        data: {
            roles: {
                rp: { active: 'Artemis 31B', chain: ['Artemis 31B'] },
                util: { active: 'Gemma 3 12B', chain: ['Gemma 3 12B'] },
                decisions: { active: 'laya_english', chain: ['laya_english'] },
            },
            shared_weights: false,
        },
    }),
    useChats: () => ({
        data: [{ id: 'chat-1', name: 'Cyberpunk Infiltration' }],
        isLoading: false,
    }),
    useLLMDirectorGates: () => ({
        data: undefined,
        isLoading: false,
    }),
}));

vi.mock('../hooks/usePipeline', () => ({
    usePipeline: () => ({
        data: {
            pipeline_name: 'Laya Canonical 6-Stage Roleplay Pipeline',
            stages: [
                { id: 'triage', stage: 'triage', owner: 'laya', target_role: 'director', name: 'Stage 1: Laya Triage & Anti-Godmoding', description: 'Routes speaker and evaluates Fate checks', model_target: 'decisions', mutates_state: false },
                { id: 'act', stage: 'act', owner: 'actor', target_role: 'rp', name: 'Stage 2: Actor Persona Generation', description: 'Generates in-character roleplay prose', model_target: 'rp', mutates_state: false },
                { id: 'audit', stage: 'audit', owner: 'laya', target_role: 'director', name: 'Stage 3: Laya Post-Turn Audit', description: 'Evaluates 16 decision gates', model_target: 'decisions', mutates_state: false },
                { id: 'update', stage: 'update', owner: 'updater', target_role: 'util', name: 'Stage 4: Statekeeper Mutation', description: 'Updater agent state modifications', model_target: 'util', mutates_state: true },
                { id: 'illustrate', stage: 'illustrate', owner: 'illustrator', target_role: 'util', name: 'Stage 5: Scene Illustrator', description: 'Generates ComfyUI image prompts', model_target: 'util', mutates_state: false },
                { id: 'chain', stage: 'chain', owner: 'laya', target_role: 'director', name: 'Stage 6: Autonomous Turn Chaining', description: 'Chains up to 4 consecutive turns', model_target: 'decisions', mutates_state: false },
            ],
            limits: {
                max_autonomous_turns: 4,
                max_continuations: 4,
                gate_threshold: 0.55,
                image_threshold: 0.65,
            },
        },
        isLoading: false,
    }),
    usePipelineQuestions: () => ({
        data: [
            { stage: 'triage', key: 'next_speaker', question: 'Who is the next speaker?', enabled: true, is_custom: false, type: 'choice' },
            { stage: 'triage', key: 'is_risky_action', question: 'Is this a risky action?', enabled: true, is_custom: false, type: 'boolean' },
        ],
        isLoading: false,
    }),
    useUpdateQuestionOverride: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCreateCustomQuestion: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDeleteQuestionOverride: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDirectorTraces: () => ({
        data: [
            {
                id: 'trace-1',
                stage: 'triage',
                turn: 1,
                selected_agent: 'character',
                created_at: '2026-10-19T10:00:00Z',
                decision: { fate_outcome: 'success', pacing_directive: 'deepen_intimacy', emotional_tone: 'tender' },
            }
        ],
        isLoading: false,
        refetch: vi.fn(),
    }),
}));

const renderStudio = () => {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <LLMStudio />
        </QueryClientProvider>
    );
};

describe('LLMStudio Page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        if (typeof window !== 'undefined') {
            window.history.replaceState({}, '', '/');
        }
    });

    it('renders the LLM Studio header and tabs', () => {
        renderStudio();
        expect(screen.getByText(/LLM Studio & Multi-Agent Workflow/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /^Workflow$/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Agent Studio/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /16-Gate Studio/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Laya Questions/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Decision Traces/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Model Cluster/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Inference & Runtime/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Workflow Simulator/i })).toBeInTheDocument();
    });

    it('navigates to Workflow Pipeline tab and renders 6-stage architecture', () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /^Workflow$/i }));
        expect(screen.getByText(/Canonical 6-Stage Roleplay Pipeline/i)).toBeInTheDocument();
        expect(screen.getByText(/Stage 1: Laya Triage & Anti-Godmoding/i)).toBeInTheDocument();
        expect(screen.getByText(/Stage 4: Statekeeper Mutation/i)).toBeInTheDocument();
    });

    it('navigates to Laya Questions tab and renders stage rubrics', () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Laya Questions/i }));
        expect(screen.getByText(/Laya System 1 Questions & Rubrics/i)).toBeInTheDocument();
        expect(screen.getByText('Who is the next speaker?')).toBeInTheDocument();
    });

    it('navigates to Decision Traces tab and shows turn telemetry', () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Decision Traces/i }));
        expect(screen.getByText(/Laya Decision Traces & Telemetry/i)).toBeInTheDocument();
        expect(screen.getByText(/Turn 1 • character/i)).toBeInTheDocument();
    });

    it('displays registered agents with built-in and custom badges', () => {
        renderStudio();
        expect(screen.getByText('Character Persona')).toBeInTheDocument();
        expect(screen.getByText('Scene Narrator')).toBeInTheDocument();
        expect(screen.getByText('Dungeon Master')).toBeInTheDocument();
        expect(screen.getAllByText(/Built-in/i).length).toBe(2);
        expect(screen.getByText('Custom', { selector: 'span' })).toBeInTheDocument();
    });

    it('navigates to the 16-Gate Studio tab and renders gate categories', () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /16-Gate Studio/i }));

        expect(screen.getByText(/Psychological & Affect/i)).toBeInTheDocument();
        expect(screen.getByText(/Embodiment & Gear/i)).toBeInTheDocument();
        expect(screen.getByText(/World & Environment/i)).toBeInTheDocument();
        expect(screen.getByText(/Progression & Stats/i)).toBeInTheDocument();
        expect(screen.getByText(/Narrative Knowledge/i)).toBeInTheDocument();

        // Check individual gate items
        expect(screen.getByText('Physical Condition')).toBeInTheDocument();
        expect(screen.getByText('Weather & Environment')).toBeInTheDocument();
        expect(screen.getByText('Quests & Goals')).toBeInTheDocument();
        expect(screen.getByText('Social Status & Standing')).toBeInTheDocument();
    });

    it('navigates to Model Cluster tab and shows the 3 roles', () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Model Cluster/i }));

        expect(screen.getByText(/Roleplay Engine \(RP\)/i)).toBeInTheDocument();
        expect(screen.getByText(/Utility Engine \(Util\)/i)).toBeInTheDocument();
        expect(screen.getByText(/Director Classifier \(Laya\)/i)).toBeInTheDocument();
        expect(screen.getByText(/Default LLM Provider & Model/i)).toBeInTheDocument();
    });

    it('navigates to Inference & Runtime tab and renders settings', async () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Inference & Runtime/i }));

        expect(screen.getByText(/Context Window & Sampling/i)).toBeInTheDocument();
        expect(screen.getByText(/Max Context Tokens/i)).toBeInTheDocument();
        expect(screen.getByText(/Temperature/i)).toBeInTheDocument();
        expect(screen.getByText(/Autobiographical Memory \(RAG\)/i)).toBeInTheDocument();
        expect(await screen.findByText(/Roleplay Default Block/i)).toBeInTheDocument();
    });

    it('runs workflow simulation and renders execution results', async () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Workflow Simulator/i }));

        const simButton = screen.getByRole('button', { name: /Run Simulation/i });
        expect(simButton).toBeInTheDocument();

        fireEvent.click(simButton);

        await waitFor(() => {
            expect(mockSimulate).toHaveBeenCalledTimes(1);
        });
        expect(mockSimulate).toHaveBeenCalledWith(expect.objectContaining({
            prompt: expect.any(String),
            stage: 'all',
            state_snapshot: { gate_threshold: 0.55, image_threshold: 0.65 },
        }));

        // Verify output display
        expect(screen.getByText('dungeon_master')).toBeInTheDocument();
        expect(screen.getByText('success_with_cost')).toBeInTheDocument();
        expect(screen.getByText(/Statekeeper Runs/i)).toBeInTheDocument();
        expect(screen.getByText(/Rendered Agent Prompt/i)).toBeInTheDocument();
        expect(screen.getByText(/variant:cinematic/i)).toBeInTheDocument();
    });

    it('switches to System 1 Director Playground and evaluates decisions', async () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Workflow Simulator/i }));

        const directorTabBtn = screen.getByRole('button', { name: /System 1 Director Playground/i });
        fireEvent.click(directorTabBtn);

        const evalBtn = screen.getByRole('button', { name: /Evaluate 13 Typed Questions/i });
        expect(evalBtn).toBeInTheDocument();

        fireEvent.click(evalBtn);

        await waitFor(() => {
            expect(mockEvaluateDirector).toHaveBeenCalledTimes(1);
        });
        expect(screen.getByText(/deepen_intimacy/i)).toBeInTheDocument();
        expect(screen.getByText(/tender/i)).toBeInTheDocument();
    });

    it('opens and submits Create Custom Agent modal', async () => {
        renderStudio();
        const createBtn = screen.getByRole('button', { name: /Create Custom Agent/i });
        fireEvent.click(createBtn);

        expect(screen.getByText('Create Custom Agent', { selector: 'h2' })).toBeInTheDocument();

        // Fill in form
        const nameInput = screen.getByPlaceholderText('e.g. Dungeon Master');
        fireEvent.change(nameInput, { target: { value: 'Story Scribe' } });

        const descInput = screen.getByPlaceholderText(/Choose this agent when/i);
        fireEvent.change(descInput, { target: { value: 'Handles historical chronicle entries' } });

        const saveBtn = screen.getByRole('button', { name: /Save Agent/i });
        fireEvent.click(saveBtn);

        await waitFor(() => {
            expect(mockCreateAgent).toHaveBeenCalledWith(expect.objectContaining({
                name: 'Story Scribe',
                slug: 'story_scribe',
                description: 'Handles historical chronicle entries',
            }));
        });
    });

    it('shows the prompt variants editor for an existing agent', () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /^Edit$/i }));

        expect(screen.getByText(/Prompt Variants \(0\)/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /New Variant/i })).toBeInTheDocument();
    });

    it('renders categorized system prompt blocks and switches categories', async () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Inference & Runtime/i }));

        expect(await screen.findByText(/27 Prompts/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Story Sandbox/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /World Vault & Memory/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Character Creator/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Prompt Studio/i })).toBeInTheDocument();

        // Switch to Story Sandbox category
        fireEvent.click(screen.getByRole('button', { name: /Story Sandbox/i }));
        expect(screen.getByText(/Story Continuation Default/i)).toBeInTheDocument();
        expect(screen.getByText(/Story Novelizer & Compiler/i)).toBeInTheDocument();

        // Switch to World Vault & Memory
        fireEvent.click(screen.getByRole('button', { name: /World Vault & Memory/i }));
        expect(screen.getByText(/World Vault Memory Extraction/i)).toBeInTheDocument();
        expect(screen.getByText(/World Architect Blueprint/i)).toBeInTheDocument();
        expect(screen.getByText(/Living World Simulation Tick/i)).toBeInTheDocument();
    });

    it('filters system prompts using search input', async () => {
        renderStudio();
        fireEvent.click(screen.getByRole('button', { name: /Inference & Runtime/i }));

        expect(await screen.findByText(/27 Prompts/i)).toBeInTheDocument();

        const searchInput = screen.getByPlaceholderText(/Search prompts or variables/i);
        fireEvent.change(searchInput, { target: { value: 'magic_prompt' } });

        expect(screen.getByText(/Magic Prompt Expander/i)).toBeInTheDocument();
        expect(screen.queryByText(/Roleplay Default Block/i)).not.toBeInTheDocument();
    });
});

