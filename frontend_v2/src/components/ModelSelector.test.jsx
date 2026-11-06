import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ModelSelector from "./ModelSelector";
import { filesApi } from "../api";

// Mock the hooks and API
vi.mock("../hooks/useInfiniteScroll", () => ({
  useInfiniteScroll: () => ({ current: null }),
}));

vi.mock("../api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
  },
  filesApi: {
    list: vi.fn().mockResolvedValue({ files: [] }),
  },
}));

// Mock toast
vi.mock("react-hot-toast", () => ({
  default: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

const renderWithProvider = (ui, options) => {
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
    options
  );
};

const lastListArgs = () => filesApi.list.mock.calls[filesApi.list.mock.calls.length - 1][0];

describe("ModelSelector Accessibility", () => {
  beforeEach(() => {
    localStorage.clear();
    queryClient.clear();
  });

  const defaultProps = {
    label: "Checkpoints",
    value: "v1-5-pruned-emaonly.ckpt",
    onChange: vi.fn(),
    directory: "models/checkpoints",
    selectedModel: {
      name: "v1-5-pruned-emaonly.ckpt",
      display_name: "SD 1.5",
      versions: [],
    },
  };

  it("renders with correct accessibility attributes on trigger button", () => {
    renderWithProvider(<ModelSelector {...defaultProps} />);

    const triggerButton = screen.getByLabelText(/Select Checkpoints/i);
    expect(triggerButton).toBeInTheDocument();
    expect(triggerButton).toHaveAttribute("aria-haspopup", "dialog");
    expect(triggerButton).toHaveAttribute("aria-expanded", "false");
  });

  it("opens modal and has correct accessibility attributes", async () => {
    renderWithProvider(<ModelSelector {...defaultProps} />);

    const triggerButton = screen.getByLabelText(/Select Checkpoints/i);
    fireEvent.click(triggerButton);

    await waitFor(() => {
      const modal = screen.getByRole("dialog");
      expect(modal).toBeInTheDocument();
      expect(modal).toHaveAttribute("aria-modal", "true");
      expect(modal).toHaveAttribute("aria-labelledby", "model-selector-title");

      const title = screen.getByText("Select Checkpoints");
      expect(title).toHaveAttribute("id", "model-selector-title");
    });
  });

  it("close button has aria-label", async () => {
    renderWithProvider(<ModelSelector {...defaultProps} autoOpen={true} />);

    const closeButton = screen.getByLabelText("Close modal");
    expect(closeButton).toBeInTheDocument();

    fireEvent.click(closeButton);

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("info button has aria-label", () => {
    const propsWithInfo = {
      ...defaultProps,
      onInfoClick: vi.fn(),
      selectedModel: {
        ...defaultProps.selectedModel,
        civitai_id: 123,
      },
    };

    renderWithProvider(<ModelSelector {...propsWithInfo} />);

    const infoButton = screen.getByLabelText(/View details for/i);
    expect(infoButton).toBeInTheDocument();
  });

  it("closes modal on Escape key press", async () => {
    renderWithProvider(<ModelSelector {...defaultProps} autoOpen={true} />);

    const modal = screen.getByRole("dialog");
    expect(modal).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape", code: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("closes modal when clicking on the backdrop", async () => {
    renderWithProvider(<ModelSelector {...defaultProps} autoOpen={true} />);

    const modal = screen.getByRole("dialog");
    expect(modal).toBeInTheDocument();

    // Click on the backdrop (the dialog itself)
    fireEvent.click(modal);

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("does NOT close modal when clicking inside the content", async () => {
    renderWithProvider(<ModelSelector {...defaultProps} autoOpen={true} />);

    const modal = screen.getByRole("dialog");
    expect(modal).toBeInTheDocument();

    // Click inside modal
    fireEvent.click(screen.getByText("Select Checkpoints"));

    // Modal should still be open
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

// The owner's complaint: "i have a hard time to find a LORA model for a
// specific character, or a pose". The picker had no way to filter by tag at
// all, and its search went to a backend that only searched name/filenames, so a
// LoRA was only findable if its filename happened to name the character.
describe("ModelSelector tag discovery", () => {
  beforeEach(() => {
    localStorage.clear();
    queryClient.clear();
    filesApi.list.mockReset();
    filesApi.list.mockResolvedValue({ files: [] });
  });

  // A LoRA whose name and filename say nothing about what it is for.
  const CHARACTER_LORA = {
    name: "unnamed_lora_v2.safetensors",
    display_name: "Untitled LoRA v2",
    model_id: "m-1",
    tags: ["character-loRA", "boob tent", "pose"],
    base_model: "Illustrious",
    type: "LORA",
  };

  const selectorProps = {
    label: "LoRAs",
    onChange: vi.fn(),
    directory: "models/loras",
    selectedModel: { name: "unnamed_lora_v2.safetensors", display_name: "Untitled LoRA v2", versions: [] },
  };

  const openWith = async (files) => {
    filesApi.list.mockResolvedValue({ files });
    renderWithProvider(<ModelSelector {...selectorProps} autoOpen={true} />);
    await waitFor(() => expect(filesApi.list).toHaveBeenCalled());
  };

  // The tag options are derived from the loaded models, so the dropdown only
  // exists after the query resolves and the component re-renders.
  const openWithTagOptions = async (files) => {
    await openWith(files);
    await screen.findByLabelText("Filter by tag, 0 selected");
  };

  const pickTag = async (tag) => {
    fireEvent.click(screen.getByLabelText(/Filter by tag, \d+ selected/));
    fireEvent.click(await screen.findByText(tag));
  };

  it("sends the typed search term so a tag can match it", async () => {
    await openWith([CHARACTER_LORA]);

    fireEvent.change(screen.getByLabelText("Search models"), {
      target: { value: "character-loRA" },
    });

    await waitFor(() => expect(lastListArgs().search).toBe("character-loRA"));
  });

  it("finds a LoRA by the character tag it carries, not by its name", async () => {
    // The backend filters on the tag; the selector's job is to ask for it.
    filesApi.list.mockImplementation(async (params) => ({
      files: params.search === "character-loRA" ? [CHARACTER_LORA] : [],
    }));
    renderWithProvider(<ModelSelector {...selectorProps} autoOpen={true} />);
    await waitFor(() => expect(filesApi.list).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Search models"), {
      target: { value: "character-loRA" },
    });

    await waitFor(() => {
      expect(screen.getByText("Untitled LoRA v2")).toBeInTheDocument();
    });
  });

  it("offers a tag dropdown built from the tags of the loaded models", async () => {
    await openWithTagOptions([CHARACTER_LORA]);

    expect(screen.getByText("character-loRA")).toBeInTheDocument();
    expect(screen.getByText("boob tent")).toBeInTheDocument();
    expect(screen.getByText("pose")).toBeInTheDocument();
  });

  it("sends the selected tags to the backend as the `tags` param", async () => {
    // The picker never sent `tags`, which is why this was the one model list
    // that could not filter by tag at all.
    await openWithTagOptions([CHARACTER_LORA]);

    await pickTag("character-loRA");

    await waitFor(() => expect(lastListArgs().tags).toBe("character-loRA"));
  });

  it("sends multiple selected tags as a comma list and shows removable pills", async () => {
    await openWithTagOptions([CHARACTER_LORA]);

    await pickTag("character-loRA");
    await pickTag("pose");

    await waitFor(() => expect(lastListArgs().tags).toBe("character-loRA,pose"));

    fireEvent.click(screen.getByLabelText("Remove tag character-loRA"));
    await waitFor(() => expect(lastListArgs().tags).toBe("pose"));
  });

  it("clears the tag filter along with the other filters", async () => {
    await openWithTagOptions([CHARACTER_LORA]);

    await pickTag("pose");
    await waitFor(() => expect(lastListArgs().tags).toBe("pose"));
    expect(screen.getByLabelText("Remove tag pose")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Clear all filters"));
    // The tag is gone from the selection, so the picker is back to unfiltered.
    // No refetch is asserted: React Query serves the unfiltered key from its
    // still-fresh cache (staleTime 5m), which is the intended behaviour.
    await waitFor(() =>
      expect(screen.queryByLabelText("Remove tag pose")).not.toBeInTheDocument()
    );
  });

  it("filters a preloaded list client-side, since there is no server to ask", async () => {
    // No `directory` means the models arrive as props, so tags and description
    // have to be matched in the browser or they are silently unsearchable.
    renderWithProvider(
      <ModelSelector
        label="LoRAs"
        onChange={vi.fn()}
        initialModels={[
          { ...CHARACTER_LORA, display_name: "Tagged By Character" },
          { name: "sunset.safetensors", display_name: "Sunset Only", tags: ["landscape"] },
        ]}
        autoOpen={true}
      />
    );

    fireEvent.change(screen.getByLabelText("Search models"), {
      target: { value: "character-loRA" },
    });

    await waitFor(() => {
      expect(screen.getAllByText("Tagged By Character").length).toBeGreaterThan(0);
      expect(screen.queryByText("Sunset Only")).not.toBeInTheDocument();
    });
  });

  it("filters a preloaded list client-side by baseModel using family-aware matching", async () => {
    renderWithProvider(
      <ModelSelector
        label="Checkpoints"
        onChange={vi.fn()}
        initialModels={[
          { name: "animagine.safetensors", display_name: "Animagine XL", base_model: "SDXL 1.0" },
          { name: "pony.safetensors", display_name: "Pony Diffusion", base_model: "Pony V7" },
          { name: "flux.safetensors", display_name: "Flux Dev", base_model: "Flux.1 D" },
          { name: "noob.safetensors", display_name: "NoobAI Checkpoint", base_model: "NoobAI" },
        ]}
        autoOpen={true}
      />
    );

    const select = screen.getByDisplayValue("All Base Models");

    // Filter by Illustrious should show NoobAI
    fireEvent.change(select, { target: { value: "Illustrious" } });
    await waitFor(() => {
      expect(screen.getAllByText("NoobAI Checkpoint").length).toBeGreaterThan(0);
      expect(screen.queryByText("Animagine XL")).not.toBeInTheDocument();
      expect(screen.queryByText("Pony Diffusion")).not.toBeInTheDocument();
    });

    // Filter by Pony should show Pony V7
    fireEvent.change(select, { target: { value: "Pony" } });
    await waitFor(() => {
      expect(screen.getAllByText("Pony Diffusion").length).toBeGreaterThan(0);
      expect(screen.queryByText("NoobAI Checkpoint")).not.toBeInTheDocument();
    });

    // Filter by Flux should show Flux.1 D
    fireEvent.change(select, { target: { value: "Flux" } });
    await waitFor(() => {
      expect(screen.getAllByText("Flux Dev").length).toBeGreaterThan(0);
      expect(screen.queryByText("Pony Diffusion")).not.toBeInTheDocument();
    });
  });
});

describe("ModelSelector persistence across modal sessions and directory isolation", () => {
  beforeEach(() => {
    localStorage.clear();
    queryClient.clear();
    filesApi.list.mockReset();
    filesApi.list.mockResolvedValue({ files: [] });
  });

  const loraProps = {
    label: "LoRAs",
    onChange: vi.fn(),
    directory: "models/loras",
    selectedModel: null,
  };

  it("persists search query in localStorage and restores it when reopening", async () => {
    const { unmount } = renderWithProvider(
      <ModelSelector {...loraProps} autoOpen={true} />
    );

    const searchInput = screen.getByLabelText("Search models");
    fireEvent.change(searchInput, { target: { value: "cat" } });

    expect(JSON.parse(localStorage.getItem("model_selector_models_loras_search"))).toBe("cat");

    // Close and unmount
    fireEvent.click(screen.getByLabelText("Close modal"));
    unmount();

    // Reopen
    renderWithProvider(<ModelSelector {...loraProps} autoOpen={true} />);
    const reopenedSearch = screen.getByLabelText("Search models");
    expect(reopenedSearch.value).toBe("cat");
  });

  it("clears search query via the search clear button", async () => {
    renderWithProvider(<ModelSelector {...loraProps} autoOpen={true} />);

    const searchInput = screen.getByLabelText("Search models");
    fireEvent.change(searchInput, { target: { value: "cat" } });

    const clearBtn = screen.getByLabelText("Clear search");
    expect(clearBtn).toBeInTheDocument();
    fireEvent.click(clearBtn);

    expect(searchInput.value).toBe("");
    expect(JSON.parse(localStorage.getItem("model_selector_models_loras_search"))).toBe("");
  });

  it("persists filters and clears them with Clear Filters button", async () => {
    renderWithProvider(<ModelSelector {...loraProps} autoOpen={true} />);

    const baseModelSelect = screen.getByDisplayValue("All Base Models");
    fireEvent.change(baseModelSelect, { target: { value: "Illustrious" } });

    expect(JSON.parse(localStorage.getItem("model_selector_models_loras_baseModel"))).toBe("Illustrious");

    const clearFiltersBtn = screen.getByLabelText("Clear all filters");
    fireEvent.click(clearFiltersBtn);

    expect(screen.getByDisplayValue("All Base Models")).toBeInTheDocument();
    expect(localStorage.getItem("model_selector_models_loras_baseModel")).toBeNull();
  });

  it("isolates saved settings across different directories", async () => {
    localStorage.setItem("model_selector_models_loras_search", JSON.stringify("lora_term"));
    localStorage.setItem("model_selector_models_checkpoints_search", JSON.stringify("checkpoint_term"));

    const { unmount } = renderWithProvider(
      <ModelSelector {...loraProps} autoOpen={true} />
    );
    expect(screen.getByLabelText("Search models").value).toBe("lora_term");
    unmount();

    renderWithProvider(
      <ModelSelector
        label="Checkpoints"
        onChange={vi.fn()}
        directory="models/checkpoints"
        autoOpen={true}
      />
    );
    expect(screen.getByLabelText("Search models").value).toBe("checkpoint_term");
  });
});
