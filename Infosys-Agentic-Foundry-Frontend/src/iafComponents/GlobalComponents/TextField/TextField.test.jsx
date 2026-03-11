import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import TextField from "./TextField";

// Mock CSS modules
jest.mock("./TextField.module.css", () => ({
  textFieldWrapper: "textFieldWrapper",
  label: "label-desc",
  inputContainer: "inputContainer",
  inputBase: "inputBase",
  inputWithIcon: "inputWithIcon",
  inputWithRightContent: "inputWithRightContent",
  inputDisabled: "inputDisabled",
  icon: "icon",
  rightContent: "rightContent",
  clearButton: "clearButton",
  searchButton: "searchButton",
}));

// Mock SVGIcons component
jest.mock("../../../Icons/SVGIcons", () => {
  return function SVGIcons({ icon, width, height, fill, stroke, color }) {
    return <span data-testid={`svg-icon-${icon}`} data-width={width} data-height={height} data-fill={fill} data-stroke={stroke} data-color={color}></span>;
  };
});

// Mock icon component for testing
const MockIcon = () => <span data-testid="custom-icon">🔍</span>;

describe("TextField Component", () => {
  const mockOnChange = jest.fn();
  const mockOnIconClick = jest.fn();
  const mockOnClear = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  // ===================
  // RENDERING TESTS
  // ===================
  describe("Rendering", () => {
    it("renders text input", () => {
      render(<TextField />);

      const input = screen.getByRole("textbox");
      expect(input).toBeInTheDocument();
      expect(input).toHaveAttribute("type", "text");
    });

    it("renders with label", () => {
      render(<TextField label="Username" />);

      expect(screen.getByText("Username")).toBeInTheDocument();
      expect(screen.getByText("Username").tagName).toBe("LABEL");
    });

    it("renders without label when not provided", () => {
      render(<TextField />);

      expect(screen.queryByRole("label-desc")).not.toBeInTheDocument();
    });

    it("renders with placeholder", () => {
      render(<TextField placeholder="Enter your name" />);

      const input = screen.getByPlaceholderText("Enter your name");
      expect(input).toBeInTheDocument();
    });

    it("renders with default empty placeholder", () => {
      render(<TextField />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveAttribute("placeholder", "");
    });

    it("renders with controlled value", () => {
      render(<TextField value="test value" onChange={mockOnChange} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveValue("test value");
    });

    it("renders wrapper with correct class", () => {
      render(<TextField label="Test" />);

      const wrapper = screen.getByText("Test").parentElement;
      expect(wrapper).toHaveClass("textFieldWrapper");
    });
  });

  // ===================
  // ICON TESTS
  // ===================
  describe("Icon", () => {
    it("renders with custom icon", () => {
      render(<TextField icon={<MockIcon />} />);

      expect(screen.getByTestId("custom-icon")).toBeInTheDocument();
    });

    it("icon is wrapped in a button", () => {
      render(<TextField icon={<MockIcon />} />);

      const iconButton = screen.getByLabelText("icon");
      expect(iconButton).toBeInTheDocument();
      expect(iconButton).toHaveAttribute("type", "button");
    });

    it("calls onIconClick when icon is clicked", () => {
      render(<TextField icon={<MockIcon />} onIconClick={mockOnIconClick} />);

      const iconButton = screen.getByLabelText("icon");
      fireEvent.click(iconButton);

      expect(mockOnIconClick).toHaveBeenCalledTimes(1);
    });

    it("icon button has tabIndex -1", () => {
      render(<TextField icon={<MockIcon />} />);

      const iconButton = screen.getByLabelText("icon");
      expect(iconButton).toHaveAttribute("tabIndex", "-1");
    });

    it("applies inputWithIcon class when icon is provided", () => {
      render(<TextField icon={<MockIcon />} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveClass("inputWithIcon");
    });

    it("does not apply inputWithIcon class when no icon", () => {
      render(<TextField />);

      const input = screen.getByRole("textbox");
      expect(input).not.toHaveClass("inputWithIcon");
    });
  });

  // ===================
  // CLEAR BUTTON TESTS
  // ===================
  describe("Clear Button", () => {
    it("shows clear button when showClearButton is true and value exists", () => {
      render(<TextField value="test" onChange={mockOnChange} showClearButton={true} onClear={mockOnClear} />);

      const clearButton = screen.getByLabelText("Clear");
      expect(clearButton).toBeInTheDocument();
    });

    it("does not show clear button when value is empty", () => {
      render(<TextField value="" onChange={mockOnChange} showClearButton={true} onClear={mockOnClear} />);

      expect(screen.queryByLabelText("Clear")).not.toBeInTheDocument();
    });

    it("does not show clear button when showClearButton is false", () => {
      render(<TextField value="test" onChange={mockOnChange} showClearButton={false} />);

      expect(screen.queryByLabelText("Clear")).not.toBeInTheDocument();
    });

    it("calls onClear when clear button is clicked", () => {
      render(<TextField value="test" onChange={mockOnChange} showClearButton={true} onClear={mockOnClear} />);

      const clearButton = screen.getByLabelText("Clear");
      fireEvent.click(clearButton);

      expect(mockOnClear).toHaveBeenCalledTimes(1);
    });

    it("clear button has correct icon", () => {
      render(<TextField value="test" onChange={mockOnChange} showClearButton={true} onClear={mockOnClear} />);

      expect(screen.getByTestId("svg-icon-x")).toBeInTheDocument();
    });

    it("clear button has tabIndex -1", () => {
      render(<TextField value="test" onChange={mockOnChange} showClearButton={true} onClear={mockOnClear} />);

      const clearButton = screen.getByLabelText("Clear");
      expect(clearButton).toHaveAttribute("tabIndex", "-1");
    });
  });

  // ===================
  // SEARCH BUTTON TESTS
  // ===================
  describe("Search Button", () => {
    it("shows search button when showSearchButton is true", () => {
      render(<TextField showSearchButton={true} onIconClick={mockOnIconClick} />);

      const searchButton = screen.getByLabelText("Search");
      expect(searchButton).toBeInTheDocument();
    });

    it("does not show search button by default", () => {
      render(<TextField />);

      expect(screen.queryByLabelText("Search")).not.toBeInTheDocument();
    });

    it("calls onIconClick when search button is clicked", () => {
      render(<TextField showSearchButton={true} onIconClick={mockOnIconClick} />);

      const searchButton = screen.getByLabelText("Search");
      fireEvent.click(searchButton);

      expect(mockOnIconClick).toHaveBeenCalledTimes(1);
    });

    it("search button has correct icon", () => {
      render(<TextField showSearchButton={true} />);

      expect(screen.getByTestId("svg-icon-search")).toBeInTheDocument();
    });

    it("search button has tabIndex -1", () => {
      render(<TextField showSearchButton={true} />);

      const searchButton = screen.getByLabelText("Search");
      expect(searchButton).toHaveAttribute("tabIndex", "-1");
    });
  });

  // ===================
  // DISABLED STATE TESTS
  // ===================
  describe("Disabled State", () => {
    it("disables input when disabled prop is true", () => {
      render(<TextField disabled={true} />);

      const input = screen.getByRole("textbox");
      expect(input).toBeDisabled();
    });

    it("applies disabled class when disabled", () => {
      render(<TextField disabled={true} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveClass("inputDisabled");
    });

    it("disables icon button when disabled", () => {
      render(<TextField icon={<MockIcon />} disabled={true} />);

      const iconButton = screen.getByLabelText("icon");
      expect(iconButton).toBeDisabled();
    });

    it("disables clear button when disabled", () => {
      render(<TextField value="test" onChange={mockOnChange} showClearButton={true} disabled={true} />);

      const clearButton = screen.getByLabelText("Clear");
      expect(clearButton).toBeDisabled();
    });

    it("disables search button when disabled", () => {
      render(<TextField showSearchButton={true} disabled={true} />);

      const searchButton = screen.getByLabelText("Search");
      expect(searchButton).toBeDisabled();
    });

    it("is enabled by default", () => {
      render(<TextField />);

      const input = screen.getByRole("textbox");
      expect(input).not.toBeDisabled();
      expect(input).not.toHaveClass("inputDisabled");
    });
  });

  // ===================
  // CHANGE HANDLER TESTS
  // ===================
  describe("Change Handler", () => {
    it("calls onChange when input value changes", () => {
      render(<TextField value="" onChange={mockOnChange} />);

      const input = screen.getByRole("textbox");
      fireEvent.change(input, { target: { value: "new value" } });

      expect(mockOnChange).toHaveBeenCalledTimes(1);
    });

    it("passes event object to onChange", () => {
      render(<TextField value="" onChange={mockOnChange} />);

      const input = screen.getByRole("textbox");
      fireEvent.change(input, { target: { value: "test" } });

      expect(mockOnChange).toHaveBeenCalledWith(expect.objectContaining({ type: "change" }));
    });
  });

  // ===================
  // CUSTOM CLASS TESTS
  // ===================
  describe("Custom Class", () => {
    it("applies additional className to input", () => {
      render(<TextField className="custom-input" />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveClass("custom-input");
      expect(input).toHaveClass("inputBase");
    });
  });

  // ===================
  // REST PROPS TESTS
  // ===================
  describe("Rest Props", () => {
    it("passes through data attributes", () => {
      render(<TextField data-testid="custom-textfield" />);

      const input = screen.getByTestId("custom-textfield");
      expect(input).toBeInTheDocument();
    });

    it("passes through aria-label", () => {
      render(<TextField aria-label="Search input" />);

      const input = screen.getByLabelText("Search input");
      expect(input).toBeInTheDocument();
    });

    it("passes through name attribute", () => {
      render(<TextField name="username" />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveAttribute("name", "username");
    });

    it("passes through id attribute", () => {
      render(<TextField id="user-input" />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveAttribute("id", "user-input");
    });

    it("passes through maxLength attribute", () => {
      render(<TextField maxLength={50} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveAttribute("maxLength", "50");
    });

    it("passes through autoComplete attribute", () => {
      render(<TextField autoComplete="off" />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveAttribute("autoComplete", "off");
    });
  });

  // ===================
  // COMBINED FEATURES TESTS
  // ===================
  describe("Combined Features", () => {
    it("renders with icon, clear button, and search button", () => {
      render(
        <TextField icon={<MockIcon />} value="test" onChange={mockOnChange} showClearButton={true} showSearchButton={true} onClear={mockOnClear} onIconClick={mockOnIconClick} />
      );

      expect(screen.getByTestId("custom-icon")).toBeInTheDocument();
      expect(screen.getByLabelText("Clear")).toBeInTheDocument();
      expect(screen.getByLabelText("Search")).toBeInTheDocument();
    });

    it("applies inputWithRightContent class when right content exists", () => {
      render(<TextField value="test" onChange={mockOnChange} showClearButton={true} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveClass("inputWithRightContent");
    });

    it("applies inputWithRightContent class when search button is shown", () => {
      render(<TextField showSearchButton={true} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveClass("inputWithRightContent");
    });

    it("does not apply inputWithRightContent class when no right content", () => {
      render(<TextField />);

      const input = screen.getByRole("textbox");
      expect(input).not.toHaveClass("inputWithRightContent");
    });

    it("all buttons work independently", () => {
      render(
        <TextField icon={<MockIcon />} value="test" onChange={mockOnChange} showClearButton={true} showSearchButton={true} onClear={mockOnClear} onIconClick={mockOnIconClick} />
      );

      const iconButton = screen.getByLabelText("icon");
      const clearButton = screen.getByLabelText("Clear");
      const searchButton = screen.getByLabelText("Search");

      fireEvent.click(iconButton);
      expect(mockOnIconClick).toHaveBeenCalledTimes(1);

      fireEvent.click(clearButton);
      expect(mockOnClear).toHaveBeenCalledTimes(1);

      fireEvent.click(searchButton);
      expect(mockOnIconClick).toHaveBeenCalledTimes(2); // onIconClick is used for both icon and search
    });
  });

  // ===================
  // EDGE CASES TESTS
  // ===================
  describe("Edge Cases", () => {
    it("renders with empty value", () => {
      render(<TextField value="" onChange={mockOnChange} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveValue("");
    });

    it("handles undefined onChange gracefully", () => {
      render(<TextField />);

      const input = screen.getByRole("textbox");
      expect(() => fireEvent.change(input, { target: { value: "test" } })).not.toThrow();
    });

    it("handles special characters in value", () => {
      render(<TextField value="<script>alert('xss')</script>" onChange={mockOnChange} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveValue("<script>alert('xss')</script>");
    });

    it("handles very long value", () => {
      const longValue = "a".repeat(1000);
      render(<TextField value={longValue} onChange={mockOnChange} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveValue(longValue);
    });

    it("handles unicode characters", () => {
      render(<TextField value="日本語テスト 🎉" onChange={mockOnChange} />);

      const input = screen.getByRole("textbox");
      expect(input).toHaveValue("日本語テスト 🎉");
    });

    it("label with special characters", () => {
      render(<TextField label="User's Email & Name" />);

      expect(screen.getByText("User's Email & Name")).toBeInTheDocument();
    });
  });

  // ===================
  // FOCUS/BLUR TESTS
  // ===================
  describe("Focus and Blur", () => {
    it("can receive focus", () => {
      render(<TextField />);

      const input = screen.getByRole("textbox");
      input.focus();

      expect(document.activeElement).toBe(input);
    });

    it("calls onFocus when focused", () => {
      const mockOnFocus = jest.fn();
      render(<TextField onFocus={mockOnFocus} />);

      const input = screen.getByRole("textbox");
      fireEvent.focus(input);

      expect(mockOnFocus).toHaveBeenCalledTimes(1);
    });

    it("calls onBlur when blurred", () => {
      const mockOnBlur = jest.fn();
      render(<TextField onBlur={mockOnBlur} />);

      const input = screen.getByRole("textbox");
      fireEvent.focus(input);
      fireEvent.blur(input);

      expect(mockOnBlur).toHaveBeenCalledTimes(1);
    });
  });

  // ===================
  // KEYBOARD INTERACTION TESTS
  // ===================
  describe("Keyboard Interaction", () => {
    it("handles keyDown event", () => {
      const mockOnKeyDown = jest.fn();
      render(<TextField onKeyDown={mockOnKeyDown} />);

      const input = screen.getByRole("textbox");
      fireEvent.keyDown(input, { key: "Enter", code: "Enter" });

      expect(mockOnKeyDown).toHaveBeenCalledTimes(1);
    });

    it("handles keyUp event", () => {
      const mockOnKeyUp = jest.fn();
      render(<TextField onKeyUp={mockOnKeyUp} />);

      const input = screen.getByRole("textbox");
      fireEvent.keyUp(input, { key: "a", code: "KeyA" });

      expect(mockOnKeyUp).toHaveBeenCalledTimes(1);
    });
  });
});
