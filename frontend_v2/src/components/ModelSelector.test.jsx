import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
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

describe("ModelSelector Accessibility", () => {
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
    render(<ModelSelector {...defaultProps} />);

    const triggerButton = screen.getByLabelText(/Select Checkpoints/i);
    expect(triggerButton).toBeInTheDocument();
    expect(triggerButton).toHaveAttribute("aria-haspopup", "dialog");
    expect(triggerButton).toHaveAttribute("aria-expanded", "false");
  });

  it("opens modal and has correct accessibility attributes", async () => {
    render(<ModelSelector {...defaultProps} />);

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
    render(<ModelSelector {...defaultProps} autoOpen={true} />);

    const closeButton = screen.getByLabelText("Close modal");
    expect(closeButton).toBeInTheDocument();

    fireEvent.click(closeButton);

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("search input has aria-label", async () => {
    render(<ModelSelector {...defaultProps} autoOpen={true} />);

    const searchInput = screen.getByLabelText("Search models");
    expect(searchInput).toBeInTheDocument();
    expect(searchInput).toHaveAttribute("type", "text");
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

    render(<ModelSelector {...propsWithInfo} />);

    const infoButton = screen.getByLabelText(/View details for/i);
    expect(infoButton).toBeInTheDocument();
  });
});
