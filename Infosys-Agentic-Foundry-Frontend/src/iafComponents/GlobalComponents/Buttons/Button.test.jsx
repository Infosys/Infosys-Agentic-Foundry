import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import Button from "./Button";

// Mock CSS modules
jest.mock("./Button.module.css", () => ({
  iafButton: "iafButton",
  iafButtonPrimary: "iafButtonPrimary",
  iafButtonSecondary: "iafButtonSecondary",
  iconOnly: "iconOnly",
  active: "active",
  iconWrapper: "iconWrapper",
  loadingSpinner: "loadingSpinner",
}));

// Mock icon component for testing
const MockIcon = () => <span data-testid="mock-icon">Icon</span>;

describe("Button Component", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // ===================
  // RENDERING TESTS
  // ===================
  describe("Rendering", () => {
    it("renders primary button by default", () => {
      render(<Button>Click Me</Button>);
      const button = screen.getByRole("button", { name: "Click Me" });

      expect(button).toBeInTheDocument();
      expect(button).toHaveClass("iafButton");
      expect(button).toHaveClass("iafButtonPrimary");
    });

    it("renders secondary button when type is secondary", () => {
      render(<Button type="secondary">Cancel</Button>);
      const button = screen.getByRole("button", { name: "Cancel" });

      expect(button).toHaveClass("iafButton");
      expect(button).toHaveClass("iafButtonSecondary");
      expect(button).not.toHaveClass("iafButtonPrimary");
    });

    it("renders icon-only button when type is icon", () => {
      render(<Button type="icon" icon={<MockIcon />} title="View" />);
      const button = screen.getByRole("button");

      expect(button).toHaveClass("iafButton");
      expect(button).toHaveClass("iconOnly");
      expect(button).toHaveAttribute("title", "View");
      expect(screen.getByTestId("mock-icon")).toBeInTheDocument();
    });

    it("renders button with icon and text for primary type", () => {
      render(
        <Button type="primary" icon={<MockIcon />}>
          Save
        </Button>
      );
      const button = screen.getByRole("button", { name: /Save/i });

      expect(button).toBeInTheDocument();
      expect(screen.getByTestId("mock-icon")).toBeInTheDocument();
      expect(screen.getByText("Save")).toBeInTheDocument();
    });

    it("renders button with icon and text for secondary type", () => {
      render(
        <Button type="secondary" icon={<MockIcon />}>
          Download
        </Button>
      );
      const button = screen.getByRole("button", { name: /Download/i });

      expect(button).toBeInTheDocument();
      expect(screen.getByTestId("mock-icon")).toBeInTheDocument();
      expect(screen.getByText("Download")).toBeInTheDocument();
    });

    it("renders button without icon when icon prop is not provided", () => {
      render(<Button>No Icon</Button>);

      expect(screen.queryByTestId("mock-icon")).not.toBeInTheDocument();
      expect(screen.getByText("No Icon")).toBeInTheDocument();
    });

    it("does not render children for icon-only button", () => {
      render(
        <Button type="icon" icon={<MockIcon />} title="Icon Button">
          Should Not Appear
        </Button>
      );

      expect(screen.queryByText("Should Not Appear")).not.toBeInTheDocument();
      expect(screen.getByTestId("mock-icon")).toBeInTheDocument();
    });
  });

  // ===================
  // DISABLED STATE TESTS
  // ===================
  describe("Disabled State", () => {
    it("disables button when disabled prop is true", () => {
      render(<Button disabled>Disabled Button</Button>);
      const button = screen.getByRole("button", { name: "Disabled Button" });

      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-disabled", "true");
    });

    it("does not trigger onClick when disabled", () => {
      const handleClick = jest.fn();
      render(
        <Button disabled onClick={handleClick}>
          Disabled
        </Button>
      );
      const button = screen.getByRole("button", { name: "Disabled" });

      fireEvent.click(button);
      expect(handleClick).not.toHaveBeenCalled();
    });

    it("is enabled by default", () => {
      render(<Button>Enabled Button</Button>);
      const button = screen.getByRole("button", { name: "Enabled Button" });

      expect(button).not.toBeDisabled();
      expect(button).toHaveAttribute("aria-disabled", "false");
    });
  });

  // ===================
  // LOADING STATE TESTS
  // ===================
  describe("Loading State", () => {
    it("shows loading spinner when loading is true", () => {
      render(<Button loading>Loading</Button>);
      const button = screen.getByRole("button");

      // Check for loading spinner SVG
      const spinner = button.querySelector("svg");
      expect(spinner).toBeInTheDocument();
      expect(spinner).toHaveClass("loadingSpinner");
    });

    it("disables button when loading is true", () => {
      render(<Button loading>Loading</Button>);
      const button = screen.getByRole("button");

      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-disabled", "true");
    });

    it("applies primary styling when loading", () => {
      render(<Button loading>Loading</Button>);
      const button = screen.getByRole("button");

      expect(button).toHaveClass("iafButtonPrimary");
    });

    it("does not show icon when loading", () => {
      render(
        <Button loading icon={<MockIcon />}>
          Loading
        </Button>
      );

      expect(screen.queryByTestId("mock-icon")).not.toBeInTheDocument();
    });

    it("still shows children text when loading for non-icon buttons", () => {
      render(<Button loading>Saving...</Button>);

      expect(screen.getByText("Saving...")).toBeInTheDocument();
    });

    it("does not trigger onClick when loading", () => {
      const handleClick = jest.fn();
      render(
        <Button loading onClick={handleClick}>
          Loading
        </Button>
      );
      const button = screen.getByRole("button");

      fireEvent.click(button);
      expect(handleClick).not.toHaveBeenCalled();
    });
  });

  // ===================
  // ACTIVE STATE TESTS
  // ===================
  describe("Active State", () => {
    it("applies active class when active prop is true", () => {
      render(<Button active>Active Button</Button>);
      const button = screen.getByRole("button", { name: "Active Button" });

      expect(button).toHaveClass("active");
    });

    it("does not apply active class by default", () => {
      render(<Button>Normal Button</Button>);
      const button = screen.getByRole("button", { name: "Normal Button" });

      expect(button).not.toHaveClass("active");
    });
  });

  // ===================
  // CLICK HANDLER TESTS
  // ===================
  describe("Click Handler", () => {
    it("calls onClick handler when clicked", () => {
      const handleClick = jest.fn();
      render(<Button onClick={handleClick}>Click Me</Button>);
      const button = screen.getByRole("button", { name: "Click Me" });

      fireEvent.click(button);
      expect(handleClick).toHaveBeenCalledTimes(1);
    });

    it("calls onClick handler with event object", () => {
      const handleClick = jest.fn();
      render(<Button onClick={handleClick}>Click Me</Button>);
      const button = screen.getByRole("button", { name: "Click Me" });

      fireEvent.click(button);
      expect(handleClick).toHaveBeenCalledWith(expect.objectContaining({ type: "click" }));
    });

    it("handles multiple clicks", () => {
      const handleClick = jest.fn();
      render(<Button onClick={handleClick}>Click Me</Button>);
      const button = screen.getByRole("button", { name: "Click Me" });

      fireEvent.click(button);
      fireEvent.click(button);
      fireEvent.click(button);
      expect(handleClick).toHaveBeenCalledTimes(3);
    });
  });

  // ===================
  // TITLE/TOOLTIP TESTS
  // ===================
  describe("Title/Tooltip", () => {
    it("renders title attribute when provided", () => {
      render(<Button title="Click to save">Save</Button>);
      const button = screen.getByRole("button", { name: "Save" });

      expect(button).toHaveAttribute("title", "Click to save");
    });

    it("icon button has title for accessibility", () => {
      render(<Button type="icon" icon={<MockIcon />} title="View Details" />);
      const button = screen.getByRole("button");

      expect(button).toHaveAttribute("title", "View Details");
    });
  });

  // ===================
  // CUSTOM CLASS TESTS
  // ===================
  describe("Custom Class", () => {
    it("accepts and applies additional className", () => {
      render(<Button className="custom-class">Custom</Button>);
      const button = screen.getByRole("button", { name: "Custom" });

      expect(button).toHaveClass("custom-class");
      expect(button).toHaveClass("iafButton");
    });

    it("combines multiple classes correctly", () => {
      render(
        <Button type="secondary" active className="extra-style">
          Styled
        </Button>
      );
      const button = screen.getByRole("button", { name: "Styled" });

      expect(button).toHaveClass("iafButton");
      expect(button).toHaveClass("iafButtonSecondary");
      expect(button).toHaveClass("active");
      expect(button).toHaveClass("extra-style");
    });
  });

  // ===================
  // REST PROPS TESTS
  // ===================
  describe("Rest Props", () => {
    it("passes through aria-label attribute", () => {
      render(<Button aria-label="Submit form">Submit</Button>);
      const button = screen.getByRole("button", { name: "Submit form" });

      expect(button).toBeInTheDocument();
    });

    it("passes through data attributes", () => {
      render(<Button data-testid="custom-button">Test</Button>);
      const button = screen.getByTestId("custom-button");

      expect(button).toBeInTheDocument();
    });

    it("always has type button to prevent form submission", () => {
      render(<Button>Button</Button>);
      const button = screen.getByRole("button", { name: "Button" });

      expect(button).toHaveAttribute("type", "button");
    });
  });

  // ===================
  // EDGE CASE TESTS
  // ===================
  describe("Edge Cases", () => {
    it("renders empty button without children", () => {
      render(<Button />);
      const button = screen.getByRole("button");

      expect(button).toBeInTheDocument();
    });

    it("handles undefined onClick gracefully", () => {
      render(<Button>No Handler</Button>);
      const button = screen.getByRole("button", { name: "No Handler" });

      expect(() => fireEvent.click(button)).not.toThrow();
    });

    it("renders correctly with complex children", () => {
      render(
        <Button>
          <span>Complex</span> <strong>Content</strong>
        </Button>
      );

      expect(screen.getByText("Complex")).toBeInTheDocument();
      expect(screen.getByText("Content")).toBeInTheDocument();
    });

    it("handles both disabled and loading props simultaneously", () => {
      render(
        <Button disabled loading>
          Both
        </Button>
      );
      const button = screen.getByRole("button");

      expect(button).toBeDisabled();
      expect(button).toHaveAttribute("aria-disabled", "true");
    });
  });

  // ===================
  // ACCESSIBILITY TESTS
  // ===================
  describe("Accessibility", () => {
    it("has correct button role", () => {
      render(<Button>Accessible</Button>);

      expect(screen.getByRole("button")).toBeInTheDocument();
    });

    it("is keyboard focusable when not disabled", () => {
      render(<Button>Focusable</Button>);
      const button = screen.getByRole("button", { name: "Focusable" });

      button.focus();
      expect(document.activeElement).toBe(button);
    });

    it("is not focusable when disabled", () => {
      render(<Button disabled>Not Focusable</Button>);
      const button = screen.getByRole("button", { name: "Not Focusable" });

      expect(button).toBeDisabled();
    });

    it("icon-only button should have title for screen readers", () => {
      render(<Button type="icon" icon={<MockIcon />} title="Delete item" aria-label="Delete item" />);
      const button = screen.getByRole("button", { name: "Delete item" });

      expect(button).toBeInTheDocument();
      expect(button).toHaveAttribute("title", "Delete item");
    });
  });
});
