import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ModelSelector from "./ModelSelector";

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

describe("ModelSelector Accessibility", () => {
  beforeEach(() => {
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
