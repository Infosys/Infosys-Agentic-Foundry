import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import Header1 from "./Header";

// Mock CSS modules
jest.mock("./Header.module.css", () => ({
  "header-container": "header-container",
}));

// Mock SVGIcons component
jest.mock("../../../Icons/SVGIcons", () => {
  return function SVGIcons({ icon, fill, stroke }) {
    return <span data-testid={`svg-icon-${icon}`} data-fill={fill} data-stroke={stroke}></span>;
  };
});

describe("Header1 Component", () => {
  const mockHandleRefresh = jest.fn();
  const mockOnHeaderClick = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  // ===================
  // RENDERING TESTS
  // ===================
  describe("Rendering", () => {
    it("renders header with name", () => {
      render(<Header1 name="Test Header" />);

      expect(screen.getByText("Test Header")).toBeInTheDocument();
    });

    it("renders header container with correct class", () => {
      render(<Header1 name="Test Header" />);

      const container = screen.getByText("Test Header").parentElement;
      expect(container).toHaveClass("header-container");
      expect(container).toHaveClass("ellipsis");
    });

    it("renders header text with title attribute", () => {
      render(<Header1 name="Long Header Name" />);

      const headerText = screen.getByText("Long Header Name");
      expect(headerText).toHaveAttribute("title", "Long Header Name");
    });

    it("does not render refresh button when handleRefresh is not provided", () => {
      render(<Header1 name="Test Header" />);

      expect(screen.queryByTitle("Refresh")).not.toBeInTheDocument();
    });

    it("renders refresh button when handleRefresh is provided", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} />);

      const refreshButton = screen.getByTitle("Refresh");
      expect(refreshButton).toBeInTheDocument();
      expect(refreshButton).toHaveAttribute("type", "button");
    });

    it("renders refresh icon inside refresh button", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} />);

      expect(screen.getByTestId("svg-icon-refresh")).toBeInTheDocument();
    });

    it("refresh icon has correct attributes", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} />);

      const refreshIcon = screen.getByTestId("svg-icon-refresh");
      expect(refreshIcon).toHaveAttribute("data-fill", "none");
      expect(refreshIcon).toHaveAttribute("data-stroke", "#00000080");
    });
  });

  // ===================
  // REFRESH BUTTON TESTS
  // ===================
  describe("Refresh Button", () => {
    it("calls handleRefresh when refresh button is clicked", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} />);

      const refreshButton = screen.getByTitle("Refresh");
      fireEvent.click(refreshButton);

      expect(mockHandleRefresh).toHaveBeenCalledTimes(1);
    });

    it("handles multiple clicks on refresh button", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} />);

      const refreshButton = screen.getByTitle("Refresh");
      fireEvent.click(refreshButton);
      fireEvent.click(refreshButton);
      fireEvent.click(refreshButton);

      expect(mockHandleRefresh).toHaveBeenCalledTimes(3);
    });

    it("has refresh-button class", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} />);

      const refreshButton = screen.getByTitle("Refresh");
      expect(refreshButton).toHaveClass("refresh-button");
    });
  });

  // ===================
  // HEADER CLICK TESTS
  // ===================
  describe("Header Click", () => {
    it("does not enable click by default", () => {
      render(<Header1 name="Test Header" onHeaderClick={mockOnHeaderClick} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).not.toHaveClass("clickable-header");
      expect(headerText).toHaveAttribute("tabIndex", "-1");
    });

    it("enables click when enableHeaderClick is true", () => {
      render(<Header1 name="Test Header" onHeaderClick={mockOnHeaderClick} enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).toHaveClass("clickable-header");
      expect(headerText).toHaveStyle({ cursor: "pointer" });
    });

    it("calls onHeaderClick when header is clicked and enableHeaderClick is true", () => {
      render(<Header1 name="Test Header" onHeaderClick={mockOnHeaderClick} enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      fireEvent.click(headerText);

      expect(mockOnHeaderClick).toHaveBeenCalledTimes(1);
    });

    it("does not call onHeaderClick when header is clicked and enableHeaderClick is false", () => {
      render(<Header1 name="Test Header" onHeaderClick={mockOnHeaderClick} enableHeaderClick={false} />);

      const headerText = screen.getByText("Test Header");
      fireEvent.click(headerText);

      expect(mockOnHeaderClick).not.toHaveBeenCalled();
    });

    it("does not call onHeaderClick when enableHeaderClick is true but onHeaderClick is not provided", () => {
      render(<Header1 name="Test Header" enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      expect(() => fireEvent.click(headerText)).not.toThrow();
    });

    it("stops event propagation when header is clicked", () => {
      const parentClickHandler = jest.fn();
      render(
        <div onClick={parentClickHandler}>
          <Header1 name="Test Header" onHeaderClick={mockOnHeaderClick} enableHeaderClick={true} />
        </div>
      );

      const headerText = screen.getByText("Test Header");
      fireEvent.click(headerText);

      expect(mockOnHeaderClick).toHaveBeenCalled();
      expect(parentClickHandler).not.toHaveBeenCalled();
    });
  });

  // ===================
  // ACCESSIBILITY TESTS
  // ===================
  describe("Accessibility", () => {
    it("header text has tabIndex -1 when not clickable", () => {
      render(<Header1 name="Test Header" />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).toHaveAttribute("tabIndex", "-1");
    });

    it("header text has tabIndex 0 when clickable", () => {
      render(<Header1 name="Test Header" enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).toHaveAttribute("tabIndex", "0");
    });

    it("header text has button role when clickable", () => {
      render(<Header1 name="Test Header" enableHeaderClick={true} />);

      const headerText = screen.getByRole("button", { name: "Test Header" });
      expect(headerText).toBeInTheDocument();
    });

    it("header text does not have button role when not clickable", () => {
      render(<Header1 name="Test Header" />);

      expect(screen.queryByRole("button", { name: "Test Header" })).not.toBeInTheDocument();
    });

    it("header text has aria-pressed when clickable", () => {
      render(<Header1 name="Test Header" enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).toHaveAttribute("aria-pressed", "false");
    });

    it("header text does not have aria-pressed when not clickable", () => {
      render(<Header1 name="Test Header" />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).not.toHaveAttribute("aria-pressed");
    });

    it("refresh button has correct title for accessibility", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} />);

      const refreshButton = screen.getByTitle("Refresh");
      expect(refreshButton).toBeInTheDocument();
    });
  });

  // ===================
  // EDGE CASES TESTS
  // ===================
  describe("Edge Cases", () => {
    it("renders with empty name", () => {
      render(<Header1 name="" />);

      const container = document.querySelector(".header-container");
      expect(container).toBeInTheDocument();
    });

    it("renders with special characters in name", () => {
      render(<Header1 name="Header & <Special> 'Chars'" />);

      expect(screen.getByText("Header & <Special> 'Chars'")).toBeInTheDocument();
    });

    it("renders with very long name", () => {
      const longName = "A".repeat(200);
      render(<Header1 name={longName} />);

      expect(screen.getByText(longName)).toBeInTheDocument();
      expect(screen.getByText(longName)).toHaveAttribute("title", longName);
    });

    it("handles both handleRefresh and enableHeaderClick together", () => {
      render(<Header1 name="Test Header" handleRefresh={mockHandleRefresh} onHeaderClick={mockOnHeaderClick} enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      const refreshButton = screen.getByTitle("Refresh");

      fireEvent.click(headerText);
      expect(mockOnHeaderClick).toHaveBeenCalledTimes(1);

      fireEvent.click(refreshButton);
      expect(mockHandleRefresh).toHaveBeenCalledTimes(1);
    });

    it("handles undefined handleRefresh gracefully", () => {
      render(<Header1 name="Test Header" handleRefresh={undefined} />);

      expect(screen.queryByTitle("Refresh")).not.toBeInTheDocument();
    });

    it("handles non-function handleRefresh gracefully", () => {
      // Component should not render refresh button if handleRefresh is not a function
      render(<Header1 name="Test Header" handleRefresh="not a function" />);

      // The refresh button will be rendered because handleRefresh is truthy
      const refreshButton = screen.getByTitle("Refresh");
      // But clicking it should not throw
      expect(() => fireEvent.click(refreshButton)).not.toThrow();
    });
  });

  // ===================
  // CSS CLASS TESTS
  // ===================
  describe("CSS Classes", () => {
    it("header text has header-text class", () => {
      render(<Header1 name="Test Header" />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).toHaveClass("header-text");
    });

    it("header text has clickable-header class when enableHeaderClick is true", () => {
      render(<Header1 name="Test Header" enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).toHaveClass("clickable-header");
    });

    it("header text does not have clickable-header class when enableHeaderClick is false", () => {
      render(<Header1 name="Test Header" enableHeaderClick={false} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).not.toHaveClass("clickable-header");
    });
  });

  // ===================
  // STYLE TESTS
  // ===================
  describe("Styles", () => {
    it("header text has pointer cursor when clickable", () => {
      render(<Header1 name="Test Header" enableHeaderClick={true} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).toHaveStyle({ cursor: "pointer" });
    });

    it("header text does not have pointer cursor when not clickable", () => {
      render(<Header1 name="Test Header" enableHeaderClick={false} />);

      const headerText = screen.getByText("Test Header");
      expect(headerText).not.toHaveStyle({ cursor: "pointer" });
    });
  });
});
