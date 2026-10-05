import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

/**
 * A failed fetch must never render as "you have nothing".
 *
 * Every case here is the same bug in a different file: a query whose `data`
 * defaults to `[]`/`undefined`, an empty state whose guard is `length === 0`,
 * and no error branch — so a 503 on GET /api/files printed "No models found"
 * beside a picker for a directory holding hundreds of files. The fix in each
 * file is a `QueryErrorState`; what is pinned here is the behaviour, not the
 * copy: an error renders the failure and never the empty state, and the empty
 * state is still there for the case that is genuinely empty.
 *
 * The structural counterpart is `test/queryErrorInvariants.test.jsx`, which stops
 * the next one being written. These cases are here because a structural scan
 * cannot tell whether the branch it finds is reachable.
 *
 * `ModelSelector` and `InstalledTab` are NOT in this file: both mock
 * `@tanstack/react-query`'s `useInfiniteQuery`, and two `vi.mock` calls for one
 * module in one file collide. They have their own files.
 */

const MODEL_FILES = [{
    model_id: 'm1',
    name: 'alpha',
    display_name: 'Alpha',
    version_id: 'v1',
    description: '',
    base_model: 'SDXL',
    type: 'Checkpoint',
    nsfw: false,
    size: 1,
    downloadUrl: '',
    file_name: 'alpha.safetensors',
    preview: null,
}];

// Several of these components hold real queries (`usePromptCategories`,
// `useCharacterMemories`, the chat workspace's own). A fresh client per render
// with retries off keeps them from reaching the network and from sharing state
// between cases.
function renderInRouter(ui) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>{ui}</MemoryRouter>
        </QueryClientProvider>
    );
}

describe('GalleryDateRail — a failed histogram fetch is not an empty gallery', () => {
    const railState = vi.hoisted(() => ({ isError: false, error: null, refetch: vi.fn(), days: [] }));

    vi.mock('../hooks/useGallery', async (importOriginal) => {
        const actual = await importOriginal();
        return {
            ...actual,
            useAssetDateHistogram: () => ({
                data: { days: railState.days, total: 0, firstDay: null, lastDay: null },
                isLoading: false,
                isError: railState.isError,
                error: railState.error,
                refetch: railState.refetch,
            }),
        };
    });

    it('states the failure instead of "No images in this view yet."', () => {
        railState.isError = true;
        railState.error = new Error('503 from the histogram');

        render(<GalleryDateRail filters={{}} onChange={() => {}} />);

        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByTestId('date-rail-empty')).toBeNull();
    });

    it('offers a retry wired to the refetch', () => {
        railState.isError = true;
        railState.refetch.mockClear();

        render(<GalleryDateRail filters={{}} onChange={() => {}} />);

        screen.getByRole('button', { name: /try again/i }).click();
        expect(railState.refetch).toHaveBeenCalled();
    });

    it('still shows the real empty copy when the fetch succeeded and there were none', () => {
        railState.isError = false;
        railState.days = [];

        render(<GalleryDateRail filters={{}} onChange={() => {}} />);

        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByTestId('date-rail-empty')).toBeTruthy();
    });

    it('shows the columns when the fetch succeeded', () => {
        railState.isError = false;
        railState.days = [{ day: '2026-01-01', count: 3 }];

        render(<GalleryDateRail filters={{}} onChange={() => {}} />);

        expect(screen.queryByTestId('date-rail-empty')).toBeNull();
        expect(screen.getByRole('button', { name: /3 images/ })).toBeTruthy();
    });
});

describe('PromptLibrary — a failed prompt fetch is not an empty library', () => {
    const promptsState = vi.hoisted(() => ({ isError: false, error: null, refetch: vi.fn(), prompts: [] }));

    vi.mock('../hooks/usePrompts', async (importOriginal) => {
        const actual = await importOriginal();
        return {
            ...actual,
            usePrompts: () => ({
                data: promptsState.prompts,
                isLoading: false,
                isError: promptsState.isError,
                error: promptsState.error,
                refetch: promptsState.refetch,
            }),
        };
    });

    it('states the failure instead of "No prompts found"', () => {
        promptsState.isError = true;
        promptsState.error = new Error('500 from /api/v2/prompts');

        renderInRouter(<PromptLibrary isOpen onClose={() => {}} />);

        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No prompts found/i)).toBeNull();
    });

    it('still shows the real empty copy when the fetch succeeded and there were none', () => {
        promptsState.isError = false;
        promptsState.prompts = [];

        renderInRouter(<PromptLibrary isOpen onClose={() => {}} />);

        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No prompts found/i)).toBeTruthy();
    });
});

describe('SceneGallery — a failed image fetch is not a gallery with no scenes', () => {
    it('states the failure instead of "No scenes generated yet"', () => {
        renderInRouter(<SceneGallery images={[]} imagesError={new Error('503')} onRetryImages={() => {}} />);

        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText('No scenes generated yet')).toBeNull();
    });

    it('still shows the real empty copy when there genuinely are no scenes', () => {
        renderInRouter(<SceneGallery images={[]} />);

        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText('No scenes generated yet')).toBeTruthy();
    });

    it('renders its images when there are some', () => {
        renderInRouter(<SceneGallery images={['a.png', 'b.png']} />);

        expect(screen.queryByText('No scenes generated yet')).toBeNull();
        expect(screen.getAllByRole('button').length).toBeGreaterThan(0);
    });
});

describe('NewChatModal — a failed lorebook fetch is not an empty lorebook shelf', () => {
    // The lorebook picker is step 3 of the wizard, so these walk to it. A
    // failure at that step used to be the most expensive kind: it is reached
    // after two clicks of sunk effort.
    function renderLorebookStep(props) {
        const utils = renderInRouter(
            <NewChatModal characters={[]} lorebooks={[]} onCreate={() => {}} onClose={() => {}} {...props} />
        );
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
        return utils;
    }

    it('states the failure instead of "No lorebooks yet"', () => {
        renderLorebookStep({ lorebooksError: new Error('503') });

        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No lorebooks yet/i)).toBeNull();
    });

    it('still shows the real empty copy when there genuinely are no lorebooks', () => {
        renderLorebookStep({});

        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No lorebooks yet/i)).toBeTruthy();
    });
});

describe('story list panels — a failed fetch is not an empty library', () => {
    it('StorySidebar states the failure instead of "No stories yet."', () => {
        render(
            <StorySidebar
                stories={[]}
                isError
                error={new Error('503')}
                onRetry={() => {}}
                onSelectStory={() => {}}
                onCreateStory={() => {}}
                onDeleteStory={() => {}}
                onImportParse={() => {}}
            />
        );
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No stories yet/i)).toBeNull();
    });

    it('StorySidebar still shows the real empty copy', () => {
        render(
            <StorySidebar
                stories={[]}
                onSelectStory={() => {}}
                onCreateStory={() => {}}
                onDeleteStory={() => {}}
                onImportParse={() => {}}
            />
        );
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No stories yet/i)).toBeTruthy();
    });

    it('ChapterSidebar states the failure instead of "No chapters yet"', () => {
        render(
            <ChapterSidebar
                chapters={[]}
                isError
                error={new Error('503')}
                onRetry={() => {}}
                onSelectChapter={() => {}}
                onCreateChapter={() => {}}
                onDeleteChapter={() => {}}
            />
        );
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No chapters yet/i)).toBeNull();
    });

    it('ChapterSidebar still shows the real empty copy', () => {
        render(
            <ChapterSidebar
                chapters={[]}
                onSelectChapter={() => {}}
                onCreateChapter={() => {}}
                onDeleteChapter={() => {}}
            />
        );
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No chapters yet/i)).toBeTruthy();
    });

    it('StoryBeatsPanel states the failure instead of "No beats recorded yet"', () => {
        render(<StoryBeatsPanel beats={[]} beatsError={new Error('503')} onRetryBeats={() => {}} onClose={() => {}} />);
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No beats recorded yet/i)).toBeNull();
    });

    it('StoryBeatsPanel still shows the real empty copy', () => {
        render(<StoryBeatsPanel beats={[]} onClose={() => {}} />);
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No beats recorded yet/i)).toBeTruthy();
    });

    it('ChapterRevisionsModal states the failure instead of "No snapshots yet"', () => {
        render(
            <ChapterRevisionsModal
                isOpen
                chapterTitle="One"
                revisions={[]}
                isError
                error={new Error('503')}
                onRetry={() => {}}
                onClose={() => {}}
            />
        );
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No snapshots yet/i)).toBeNull();
    });

    it('ChapterRevisionsModal still shows the real empty copy', () => {
        render(<ChapterRevisionsModal isOpen chapterTitle="One" revisions={[]} onClose={() => {}} />);
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No snapshots yet/i)).toBeTruthy();
    });
});

describe('SystemPromptPanel — a failed prompt fetch is not an unassembled prompt', () => {
    it('states the failure instead of "No system prompt sections assembled yet."', () => {
        render(
            <SystemPromptPanel
                activeChat={{ id: 'c1' }}
                systemPromptData={undefined}
                systemPromptError={new Error('503')}
                onRetrySystemPrompt={() => {}}
            />
        );
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No system prompt sections assembled yet/i)).toBeNull();
    });

    it('still shows the real empty copy when the prompt genuinely has no sections', () => {
        render(<SystemPromptPanel activeChat={{ id: 'c1' }} systemPromptData={{ sections: [] }} />);
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No system prompt sections assembled yet/i)).toBeTruthy();
    });
});

describe('ModelTagFilter — a failed model fetch is not a library with no tags', () => {
    it('states the failure instead of "No tags on the loaded models yet."', () => {
        render(
            <ModelTagFilter
                availableTags={[]}
                selectedTags={[]}
                onSelectedTagsChange={() => {}}
                tagsError={new Error('503')}
            />
        );
        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.queryByText(/No tags on the loaded models yet/i)).toBeNull();
    });

    it('still shows the real empty copy when the loaded models genuinely carry no tags', () => {
        render(<ModelTagFilter availableTags={[]} selectedTags={[]} onSelectedTagsChange={() => {}} />);
        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No tags on the loaded models yet/i)).toBeTruthy();
    });
});

describe('AssetTagEditor — the failure it already handled now offers a retry', () => {
    const assetTagsState = vi.hoisted(() => ({ isError: false, error: null, refetch: vi.fn(), tags: [] }));

    vi.mock('../hooks/useAssetTags', async (importOriginal) => {
        const actual = await importOriginal();
        return {
            ...actual,
            useAssetTags: () => ({
                data: { tags: assetTagsState.tags },
                isLoading: false,
                isError: assetTagsState.isError,
                error: assetTagsState.error,
                refetch: assetTagsState.refetch,
            }),
            useAddAssetTag: () => ({ mutateAsync: vi.fn(), isPending: false }),
            useRemoveAssetTag: () => ({ mutateAsync: vi.fn(), isPending: false }),
            useTagVocabulary: () => ({ data: [] }),
        };
    });

    it('offers a retry wired to the refetch, and still states the failure', () => {
        assetTagsState.isError = true;
        assetTagsState.error = new Error('503');
        assetTagsState.refetch.mockClear();

        render(<AssetTagEditor assetId="a1" />);

        expect(screen.getByRole('alert')).toBeTruthy();
        expect(screen.getByText(/503/)).toBeTruthy();
        screen.getByRole('button', { name: /try again/i }).click();
        expect(assetTagsState.refetch).toHaveBeenCalled();
    });

    it('still shows the real empty copy when there genuinely are no tags', () => {
        assetTagsState.isError = false;
        assetTagsState.tags = [];

        render(<AssetTagEditor assetId="a1" />);

        expect(screen.queryByRole('alert')).toBeNull();
        expect(screen.getByText(/No tags yet/i)).toBeTruthy();
    });
});

describe('ChatContextPanel — a failed job fetch is not a chat with no jobs', () => {
    // The panel takes no props: everything, including `queryErrors`, comes from
    // the workspace context. That is why this defect was invisible from the
    // panel's own signature — the only way to see a failure here is through the
    // context the provider publishes.
    const workspace = vi.hoisted(() => ({ value: {} }));

    vi.mock('../contexts/ChatWorkspaceContext', () => ({
        useChatWorkspace: () => workspace.value,
        ChatWorkspaceProvider: ({ children }) => children,
    }));

    function renderPanel(overrides) {
        workspace.value = {
            activeChat: null,
            linkedCharacter: null,
            chatJobs: [],
            chatCollection: null,
            activeStreamEntries: [],
            sceneJobId: null,
            characters: [],
            lorebooks: [],
            selectedLorebooks: [],
            patchCharacterMutation: {},
            systemPromptData: null,
            availableModels: [],
            defaultLlmConfig: null,
            setShowCharacterDetails: () => {},
            setShowScenesModal: () => {},
            handleChatUpdate: () => {},
            voices: [],
            queryErrors: {},
            messages: [],
            ...overrides,
        };
        return renderInRouter(<ChatContextPanel />);
    }

    it('states the failure instead of "No jobs tracked for this chat yet."', () => {
        renderPanel({
            queryErrors: { chatJobs: { noun: 'chat jobs', error: new Error('503'), refetch: () => {} } },
        });

        expect(screen.getAllByRole('alert').some((el) => /chat jobs/i.test(el.textContent))).toBe(true);
        expect(screen.queryByText(/No jobs tracked for this chat yet/i)).toBeNull();
    });

    it('still shows the real empty copy when the chat genuinely has no jobs', () => {
        renderPanel({});

        expect(screen.getByText(/No jobs tracked for this chat yet/i)).toBeTruthy();
    });
});

// `MODEL_FILES` is shared with the two `useInfiniteQuery` files' fixtures and
// kept here so the shape of a file row stays in one place.
export const MODEL_FIXTURE = MODEL_FILES;

import GalleryDateRail from '../components/dashboard/GalleryDateRail';
import PromptLibrary from '../components/generator/PromptLibrary';
import SceneGallery from '../components/SceneGallery';
import NewChatModal from '../components/chat/NewChatModal';
import StorySidebar from '../components/story/StorySidebar';
import ChapterSidebar from '../components/story/ChapterSidebar';
import StoryBeatsPanel from '../components/story/StoryBeatsPanel';
import ChapterRevisionsModal from '../components/story/ChapterRevisionsModal';
import SystemPromptPanel from '../components/chat/SystemPromptPanel';
import ModelTagFilter from '../components/selector/ModelTagFilter';
import AssetTagEditor from '../components/dashboard/AssetTagEditor';
import ChatContextPanel from '../components/chat/ChatContextPanel';
import { ChatWorkspaceProvider } from '../contexts/ChatWorkspaceContext';