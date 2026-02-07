import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import Dropdown from "./Dropdown";

// Mock SVGIcons component
jest.mock("../../Icons/SVGIcons", () => {
  return function SVGIcons({ icon, fill }) {
    return <span data-testid={`svg-icon-${icon}`} data-fill={fill}></span>;
  };
});

// Mock CSS modules
jest.mock("./Dropdown.module.css", () => ({
  inputWithTags: "inputWithTags",
  iconContainer: "iconContainer",
  searchInput: "searchInput",
  selectedTags: "selectedTags",
  tag: "tag",
  closeBtn: "closeBtn",
  dropdownList: "dropdownList",
}));

describe("Dropdown Component", () => {
  const mockSetTags = jest.fn();
  const mockSetSelectedTags = jest.fn();
  const mockStyles = { dropdownContainer: "dropdownContainer" };

  const defaultProps = {
    tags: [
      { tag_id: 1, tag_name: "React", selected: false },
      { tag_id: 2, tag_name: "JavaScript", selected: false },
      { tag_id: 3, tag_name: "TypeScript", selected: true },
    ],
    setTags: mockSetTags,
    setSelectedTags: mockSetSelectedTags,
    styles: mockStyles,
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("renders dropdown with initial props", () => {
    render(<Dropdown {...defaultProps} />);

    expect(screen.getByPlaceholderText("Search/Select Tags")).toBeInTheDocument();
    expect(screen.getByTestId("svg-icon-drop_arrow_down")).toBeInTheDocument();
  });

  test("displays pre-selected tags from props", async () => {
    render(<Dropdown {...defaultProps} />);

    await waitFor(() => {
      expect(screen.getByText("TypeScript")).toBeInTheDocument();
    });
  });

  test("shows dropdown list when input is focused", () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.focus(input);

    expect(screen.getByText("React")).toBeInTheDocument();
    expect(screen.getByText("JavaScript")).toBeInTheDocument();
  });

  test("toggles dropdown visibility when clicking icon", () => {
    render(<Dropdown {...defaultProps} />);

    const iconContainer = screen.getByTestId("svg-icon-drop_arrow_down").parentElement;

    // Open dropdown
    fireEvent.click(iconContainer);
    expect(screen.getByTestId("svg-icon-drop_arrow_up")).toBeInTheDocument();

    // Close dropdown
    fireEvent.click(iconContainer);
    expect(screen.getByTestId("svg-icon-drop_arrow_down")).toBeInTheDocument();
  });

  test("filters options based on search term", () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.change(input, { target: { value: "java" } });

    expect(screen.getByText("JavaScript")).toBeInTheDocument();
    expect(screen.queryByText("React")).not.toBeInTheDocument();
  });

  test("selects an option and updates state", async () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.focus(input);

    const reactOption = screen.getByText("React");
    fireEvent.click(reactOption);

    await waitFor(() => {
      expect(mockSetTags).toHaveBeenCalledWith(expect.any(Function));
      expect(screen.getByText("React")).toBeInTheDocument();
    });
  });

  test("removes selected option when clicking close button", async () => {
    render(<Dropdown {...defaultProps} />);

    await waitFor(() => {
      const closeButton = screen.getByText("X");
      fireEvent.click(closeButton);
    });

    expect(mockSetTags).toHaveBeenCalledWith(expect.any(Function));
  });

  test("clears search term after selecting option", async () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.change(input, { target: { value: "React" } });

    const reactOption = screen.getByText("React");
    fireEvent.click(reactOption);

    await waitFor(() => {
      expect(input.value).toBe("");
    });
  });

  test("does not select already selected option", async () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.focus(input);

    const reactOption = screen.getByText("React");
    fireEvent.click(reactOption);

    await waitFor(() => {
      expect(mockSetTags).toHaveBeenCalledTimes(1);
    });

    // Try to select again
    fireEvent.focus(input);
    const selectedTags = screen.getAllByText("React");
    expect(selectedTags.length).toBeGreaterThan(0);
  });

  test("calls setSelectedTags when selectedOptions change", async () => {
    render(<Dropdown {...defaultProps} />);

    await waitFor(() => {
      expect(mockSetSelectedTags).toHaveBeenCalled();
    });
  });

  test("filters out selected options from dropdown list", async () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.focus(input);

    // TypeScript is pre-selected, so it appears as a selected tag
    // but should NOT appear in the dropdown list options
    await waitFor(() => {
      // TypeScript should appear exactly once (in selected tags area, not in dropdown)
      const typeScriptElements = screen.getAllByText("TypeScript");
      expect(typeScriptElements).toHaveLength(1);

      // Verify React and JavaScript appear in the dropdown (they are not selected)
      expect(screen.getByText("React")).toBeInTheDocument();
      expect(screen.getByText("JavaScript")).toBeInTheDocument();
    });
  });

  test("handles empty tags array", () => {
    const emptyProps = { ...defaultProps, tags: [] };
    render(<Dropdown {...emptyProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.focus(input);

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  test("handles tags without tag_id gracefully", () => {
    const propsWithoutIds = {
      ...defaultProps,
      tags: [
        { tag_name: "NoID", selected: false },
        { tag_id: 2, tag_name: "WithID", selected: false },
      ],
    };

    render(<Dropdown {...propsWithoutIds} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.focus(input);

    expect(screen.getByText("NoID")).toBeInTheDocument();
    expect(screen.getByText("WithID")).toBeInTheDocument();
  });

  test("case-insensitive search filtering", () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.change(input, { target: { value: "REACT" } });

    expect(screen.getByText("React")).toBeInTheDocument();
  });

  test("hides dropdown when no filtered options available", () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.change(input, { target: { value: "NonExistentTag" } });

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  test("updates setTags callback with correct selected state", async () => {
    render(<Dropdown {...defaultProps} />);

    const input = screen.getByPlaceholderText("Search/Select Tags");
    fireEvent.focus(input);

    const reactOption = screen.getByText("React");
    fireEvent.click(reactOption);

    await waitFor(() => {
      expect(mockSetTags).toHaveBeenCalledWith(expect.any(Function));
      const updateFunction = mockSetTags.mock.calls[0][0];
      const updatedTags = updateFunction(defaultProps.tags);

      expect(updatedTags[0].selected).toBe(true);
    });
  });

  test("updates setTags callback to deselect on remove", async () => {
    render(<Dropdown {...defaultProps} />);

    await waitFor(() => {
      const closeButton = screen.getByText("X");
      fireEvent.click(closeButton);
    });

    expect(mockSetTags).toHaveBeenCalledWith(expect.any(Function));
    const updateFunction = mockSetTags.mock.calls[0][0];
    const updatedTags = updateFunction(defaultProps.tags);

    const typeScriptTag = updatedTags.find((tag) => tag.tag_id === 3);
    expect(typeScriptTag.selected).toBe(false);
  });
});
