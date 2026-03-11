import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef } from "react";
import ChatPanel from "./ChatPanel";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios";
import { useChatServices } from "../../services/chatService";
import Cookies from "js-cookie";

// Mock dependencies
jest.mock("../../Hooks/MessageContext");
jest.mock("../../Hooks/useAxios");
jest.mock("../../services/chatService");
jest.mock("js-cookie");
jest.mock("../../utils/sanitization", () => ({
  sanitizeInput: (val) => val,
}));
jest.mock("../../Icons/SVGIcons", () => ({
  __esModule: true,
  default: ({ icon }) => <div data-testid={`svg-icon-${icon}`}>{icon}</div>,
}));
jest.mock("../../iafComponents/GlobalComponents/Buttons/Button", () => ({
  __esModule: true,
  default: ({ children, onClick, type }) => (
    <button onClick={onClick} data-testid={`iaf-button-${type}`}>
      {children}
    </button>
  ),
}));
jest.mock("./CodeEditor", () => ({
  __esModule: true,
  default: ({ codeToDisplay, readOnly }) => (
    <div data-testid="code-editor" data-readonly={readOnly}>
      {codeToDisplay}
    </div>
  ),
}));

// Mock NewCommonDropdown to render a native <select> for testability
jest.mock("./NewCommonDropdown", () => ({
  __esModule: true,
  default: ({ options, selected, onSelect, disabled }) => (
    <select
      data-testid="model-dropdown"
      value={selected}
      onChange={(e) => onSelect(e.target.value)}
      disabled={disabled}
      title="Select AI model"
    >
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  ),
}));

describe("ChatPanel Component", () => {
  // Constants
  const MODEL_COUNT = 3;
  const LAST_MODEL_INDEX = 2;
  const DELAYED_RESPONSE_MS = 100;

  // Mock functions
  let mockAddMessage;
  let mockFetchData;
  let mockPostData;
  let mockDeleteData;
  let mockResetChat;
  let mockFetchNewChats;

  // Default props
  const defaultProps = {
    messages: [],
    setMessages: jest.fn(),
    pipelineId: "test-pipeline-123",
    models: ["gpt-4", "gpt-3.5-turbo", "claude-3"],
    onCodeUpdate: jest.fn(),
    onClose: jest.fn(),
    codeSnippet: "def test_function():\n    pass",
    toolId: "tool-123",
    chatSessionId: "",
    onSessionIdChange: jest.fn(),
  };

  beforeEach(() => {
    // Reset all mocks
    jest.clearAllMocks();

    // Setup mock implementations
    mockAddMessage = jest.fn();
    mockFetchData = jest.fn();
    mockPostData = jest.fn();
    mockDeleteData = jest.fn();
    mockResetChat = jest.fn();
    mockFetchNewChats = jest.fn();

    useMessage.mockReturnValue({ addMessage: mockAddMessage });
    useFetch.mockReturnValue({
      fetchData: mockFetchData,
      postData: mockPostData,
      deleteData: mockDeleteData,
    });
    useChatServices.mockReturnValue({
      resetChat: mockResetChat,
      fetchNewChats: mockFetchNewChats,
    });

    Cookies.get.mockImplementation((key) => {
      const cookies = {
        email: "test@example.com",
        userName: "TestUser",
        role: "USER",
      };
      return cookies[key] || null;
    });
  });

  describe("Component Rendering", () => {
    test("should render ChatPanel with all main sections", () => {
      render(<ChatPanel {...defaultProps} />);

      expect(screen.getByText("Code Assistant")).toBeInTheDocument();
      expect(screen.getByPlaceholderText("Ask about your code...")).toBeInTheDocument();
      expect(screen.getByTitle("Send message")).toBeInTheDocument();
    });

    test("should display empty state when no messages", () => {
      render(<ChatPanel {...defaultProps} />);

      expect(screen.getByText("AI Code Assistant")).toBeInTheDocument();
      expect(screen.getByText("Generate, refactor, or debug your code")).toBeInTheDocument();
    });

    test("should render model selection dropdown with available models", () => {
      render(<ChatPanel {...defaultProps} />);

      const modelSelect = screen.getByTestId("model-dropdown");
      expect(modelSelect).toBeInTheDocument();

      const options = screen.getAllByRole("option");
      expect(options).toHaveLength(MODEL_COUNT);
      expect(options[0]).toHaveTextContent("gpt-4");
      expect(options[1]).toHaveTextContent("gpt-3.5-turbo");
      expect(options[LAST_MODEL_INDEX]).toHaveTextContent("claude-3");
    });

    test("should select first model by default", () => {
      render(<ChatPanel {...defaultProps} />);

      const modelSelect = screen.getByTestId("model-dropdown");
      expect(modelSelect.value).toBe("gpt-4");
    });

    test("should render close button in header", () => {
      render(<ChatPanel {...defaultProps} />);

      const closeButton = screen.getByTitle("Close chat panel");
      expect(closeButton).toBeInTheDocument();
      expect(closeButton).toHaveTextContent("×");
    });
  });

  describe("Message Handling", () => {
    test("should display existing messages", () => {
      const messagesWithContent = [
        {
          id: 1,
          role: "user",
          content: "Hello, can you help me?",
          timestamp: new Date().toISOString(),
        },
        {
          id: 2,
          role: "assistant",
          content: "Of course! How can I assist you today?",
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithContent} setMessages={jest.fn()} />);

      expect(screen.getByText("Hello, can you help me?")).toBeInTheDocument();
      expect(screen.getByText("Of course! How can I assist you today?")).toBeInTheDocument();
    });

    test("should send message when send button is clicked", async () => {
      mockPostData.mockResolvedValue({
        message: "Here is the response",
        code_snippet: null,
      });

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      const sendButton = screen.getByTitle("Send message");

      await userEvent.type(input, "Write a test function");
      await userEvent.click(sendButton);

      await waitFor(() => {
        expect(mockPostData).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            pipeline_id: "test-pipeline-123",
            query: "Write a test function",
            model_name: "gpt-4",
          })
        );
      });
    });

    test("should send message on Enter key press", async () => {
      mockPostData.mockResolvedValue({
        message: "Response from API",
        code_snippet: null,
      });

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");

      await userEvent.type(input, "Test message{Enter}");

      await waitFor(() => {
        expect(mockPostData).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            query: "Test message",
          })
        );
      });
    });

    test("should not send message on Shift+Enter", async () => {
      render(<ChatPanel {...defaultProps} />);

      const input = screen.getByPlaceholderText("Ask about your code...");

      await userEvent.type(input, "Test message");
      fireEvent.keyDown(input, { key: "Enter", shiftKey: true });

      await waitFor(() => {
        expect(mockPostData).not.toHaveBeenCalled();
      });
    });

    test("should clear input after sending message", async () => {
      mockPostData.mockResolvedValue({
        message: "Response",
        code_snippet: null,
      });

      render(<ChatPanel {...defaultProps} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      const sendButton = screen.getByTitle("Send message");

      await userEvent.type(input, "Test input");
      expect(input.value).toBe("Test input");

      await userEvent.click(sendButton);

      await waitFor(() => {
        expect(input.value).toBe("");
      });
    });

    test("should disable send button when input is empty", () => {
      render(<ChatPanel {...defaultProps} />);

      const sendButton = screen.getByTitle("Send message");
      expect(sendButton).toBeDisabled();
    });

    test("should enable send button when input has text", async () => {
      render(<ChatPanel {...defaultProps} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      const sendButton = screen.getByTitle("Send message");

      await userEvent.type(input, "Some text");

      expect(sendButton).not.toBeDisabled();
    });
  });

  describe("Code Update Functionality", () => {
    test("should call onCodeUpdate when response contains code_snippet with def", async () => {
      const onCodeUpdateMock = jest.fn();
      const codeSnippet = "def new_function():\n    return 'test'";

      mockPostData.mockResolvedValue({
        message: "Here is your code",
        code_snippet: codeSnippet,
        version_number: 1,
      });

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} onCodeUpdate={onCodeUpdateMock} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      await userEvent.type(input, "Generate function");
      await userEvent.click(screen.getByTitle("Send message"));

      await waitFor(() => {
        expect(onCodeUpdateMock).toHaveBeenCalledWith(codeSnippet);
      });
    });

    test("should not call onCodeUpdate when code_snippet does not contain def", async () => {
      const onCodeUpdateMock = jest.fn();

      mockPostData.mockResolvedValue({
        message: "Here is a comment",
        code_snippet: "# Just a comment",
        version_number: 1,
      });

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} onCodeUpdate={onCodeUpdateMock} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      await userEvent.type(input, "Add comment");
      await userEvent.click(screen.getByTitle("Send message"));

      await waitFor(() => {
        expect(mockPostData).toHaveBeenCalled();
      });

      expect(onCodeUpdateMock).not.toHaveBeenCalled();
    });

    test("should show restore code button for messages with code_snippet", () => {
      const messagesWithCode = [
        {
          id: 1,
          role: "assistant",
          content: "Here is your function",
          code_snippet: "def example():\n    pass",
          version_number: 1,
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithCode} setMessages={jest.fn()} />);

      expect(screen.getByText("Restore Code")).toBeInTheDocument();
    });

    test("should restore code when restore button is clicked", async () => {
      const onCodeUpdateMock = jest.fn();
      const codeSnippet = "def restore_me():\n    return True";

      const messagesWithCode = [
        {
          id: 1,
          role: "assistant",
          content: "Previous code",
          code_snippet: codeSnippet,
          version_number: 1,
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithCode} setMessages={jest.fn()} onCodeUpdate={onCodeUpdateMock} />);

      const restoreButton = screen.getByText("Restore Code");
      await userEvent.click(restoreButton);

      expect(onCodeUpdateMock).toHaveBeenCalledWith(codeSnippet);
    });
  });

  describe("Model Selection", () => {
    test("should update selected model when dropdown changes", async () => {
      render(<ChatPanel {...defaultProps} />);

      const modelSelect = screen.getByTestId("model-dropdown");

      await userEvent.selectOptions(modelSelect, "gpt-3.5-turbo");

      expect(modelSelect.value).toBe("gpt-3.5-turbo");
    });

    test("should send message with selected model", async () => {
      mockPostData.mockResolvedValue({
        message: "Response",
        code_snippet: null,
      });

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} setMessages={setMessagesMock} />);

      const modelSelect = screen.getByTestId("model-dropdown");
      await userEvent.selectOptions(modelSelect, "claude-3");

      const input = screen.getByPlaceholderText("Ask about your code...");
      await userEvent.type(input, "Test with claude");
      await userEvent.click(screen.getByTitle("Send message"));

      await waitFor(() => {
        expect(mockPostData).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            model_name: "claude-3",
          })
        );
      });
    });

    test("should handle models as array of objects with label property", () => {
      const modelObjects = [{ label: "GPT-4" }, { label: "Claude-3" }, { label: "Gemini" }];

      render(<ChatPanel {...defaultProps} models={modelObjects} />);

      const options = screen.getAllByRole("option");
      expect(options).toHaveLength(MODEL_COUNT);
      expect(options[0]).toHaveTextContent("GPT-4");
      expect(options[1]).toHaveTextContent("Claude-3");
      expect(options[LAST_MODEL_INDEX]).toHaveTextContent("Gemini");
    });
  });

  describe("Clear Chat Functionality", () => {
    test("should clear chat and reset conversation", async () => {
      mockDeleteData.mockResolvedValue({ success: true });
      mockResetChat.mockResolvedValue({ success: true });
      mockFetchNewChats.mockResolvedValue("new-session-123");
      mockPostData.mockResolvedValue({
        message: "Welcome back!",
        code_snippet: null,
      });

      const messagesWithContent = [
        { id: 1, role: "user", content: "Hello", timestamp: new Date().toISOString() },
        { id: 2, role: "assistant", content: "Hi there", timestamp: new Date().toISOString() },
      ];

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} messages={messagesWithContent} setMessages={setMessagesMock} />);

      const clearButton = screen.getByTitle("Clear chat");
      await userEvent.click(clearButton);

      await waitFor(() => {
        expect(setMessagesMock).toHaveBeenCalledWith([]);
      });
      expect(mockDeleteData).toHaveBeenCalled();
      expect(mockResetChat).toHaveBeenCalled();
    });

    test("should disable clear button when no messages", () => {
      render(<ChatPanel {...defaultProps} />);

      const clearButton = screen.getByTitle("Clear chat");
      expect(clearButton).toBeDisabled();
    });

    test("should enable clear button when messages exist", () => {
      const messagesWithContent = [{ id: 1, role: "user", content: "Test", timestamp: new Date().toISOString() }];

      render(<ChatPanel {...defaultProps} messages={messagesWithContent} setMessages={jest.fn()} />);

      const clearButton = screen.getByTitle("Clear chat");
      expect(clearButton).not.toBeDisabled();
    });
  });

  describe("Loading States", () => {
    test("should show loading state when sending message", async () => {
      mockPostData.mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(
              () =>
                resolve({
                  message: "Response",
                  code_snippet: null,
                }),
              DELAYED_RESPONSE_MS
            )
          )
      );

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      await userEvent.type(input, "Test message");
      await userEvent.click(screen.getByTitle("Send message"));

      // Input should be disabled during loading
      expect(input).toBeDisabled();
    });

    test("should disable input during loading", async () => {
      mockPostData.mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(
              () =>
                resolve({
                  message: "Response",
                }),
              DELAYED_RESPONSE_MS
            )
          )
      );

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      await userEvent.type(input, "Test");
      await userEvent.click(screen.getByTitle("Send message"));

      // Input should be disabled during loading
      expect(input).toBeDisabled();
    });
  });

  describe("Error Handling", () => {
    test("should display error message when API call fails", async () => {
      mockPostData.mockRejectedValue(new Error("API Error"));

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      await userEvent.type(input, "Test error");
      await userEvent.click(screen.getByTitle("Send message"));

      await waitFor(() => {
        expect(mockAddMessage).toHaveBeenCalledWith("Failed to get response. Please try again.", "error");
      });
    });

    test("should add error message to chat when API fails", async () => {
      mockPostData.mockRejectedValue(new Error("Network Error"));

      const setMessagesMock = jest.fn();
      render(<ChatPanel {...defaultProps} setMessages={setMessagesMock} />);

      const input = screen.getByPlaceholderText("Ask about your code...");
      await userEvent.type(input, "Test");
      await userEvent.click(screen.getByTitle("Send message"));

      await waitFor(() => {
        // ChatPanel uses functional updater: setMessages((prev) => [...prev, errorMsg])
        expect(setMessagesMock).toHaveBeenCalledWith(expect.any(Function));
      });
    });
  });

  describe("Code Preview Modal", () => {
    test("should open code preview modal when version icon is clicked", async () => {
      const messagesWithCode = [
        {
          id: 1,
          role: "assistant",
          content: "Code generated",
          code_snippet: "def preview_code():\n    return 'preview'",
          version_number: 1,
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithCode} setMessages={jest.fn()} />);

      const versionNumber = screen.getByText("1");
      await userEvent.click(versionNumber);

      await waitFor(() => {
        expect(screen.getByText("Code Preview")).toBeInTheDocument();
      });
      expect(screen.getByTestId("code-editor")).toBeInTheDocument();
    });

    test("should close modal when close button is clicked", async () => {
      const messagesWithCode = [
        {
          id: 1,
          role: "assistant",
          content: "Code",
          code_snippet: "def close_test():\n    pass",
          version_number: 1,
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithCode} setMessages={jest.fn()} />);

      const versionNumber = screen.getByText("1");
      await userEvent.click(versionNumber);

      const closeButton = screen.getByTitle("Close modal");
      await userEvent.click(closeButton);

      await waitFor(() => {
        expect(screen.queryByText("Code Preview")).not.toBeInTheDocument();
      });
    });

    test("should restore code from modal and close", async () => {
      const onCodeUpdateMock = jest.fn();
      const codeSnippet = "def modal_restore():\n    return 'restored'";

      const messagesWithCode = [
        {
          id: 1,
          role: "assistant",
          content: "Code",
          code_snippet: codeSnippet,
          version_number: 1,
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithCode} setMessages={jest.fn()} onCodeUpdate={onCodeUpdateMock} />);

      const versionNumber = screen.getByText("1");
      await userEvent.click(versionNumber);

      const restoreButton = screen.getByTestId("iaf-button-primary");
      await userEvent.click(restoreButton);

      expect(onCodeUpdateMock).toHaveBeenCalledWith(codeSnippet);
      await waitFor(() => {
        expect(screen.queryByText("Code Preview")).not.toBeInTheDocument();
      });
    });
  });

  describe("Close Functionality", () => {
    test("should call onClose when close button is clicked", async () => {
      const onCloseMock = jest.fn();
      render(<ChatPanel {...defaultProps} onClose={onCloseMock} />);

      const closeButton = screen.getByTitle("Close chat panel");
      await userEvent.click(closeButton);

      expect(onCloseMock).toHaveBeenCalledTimes(1);
    });
  });

  describe("Session Management", () => {
    test("should generate session ID from email and toolId", () => {
      render(<ChatPanel {...defaultProps} chatSessionId="" />);

      expect(Cookies.get).toHaveBeenCalledWith("email");
    });

    test("should use external chatSessionId when provided", () => {
      render(<ChatPanel {...defaultProps} chatSessionId="external-session-123" />);

      // Component should use the external session ID
      expect(screen.getByText("Code Assistant")).toBeInTheDocument();
    });

    test("should call onSessionIdChange when new session is created", async () => {
      const onSessionIdChangeMock = jest.fn();
      mockFetchNewChats.mockResolvedValue("new-session-456");
      mockPostData.mockResolvedValue({
        message: "Welcome",
        code_snippet: null,
      });

      render(<ChatPanel {...defaultProps} toolId="" onSessionIdChange={onSessionIdChangeMock} />);

      await waitFor(() => {
        expect(mockFetchNewChats).toHaveBeenCalled();
      });
    });
  });

  describe("Explain Code Functionality", () => {
    test("should handle explain code via ref method", async () => {
      mockPostData.mockResolvedValue({
        message: "Code explanation",
        code_snippet: null,
      });

      const TestWrapper = () => {
        const chatRef = useRef(null);

        return (
          <div>
            <ChatPanel {...defaultProps} ref={chatRef} />
            <button onClick={() => chatRef.current?.explainCode("const x = 5;")}>Explain</button>
          </div>
        );
      };

      render(<TestWrapper />);

      const explainButton = screen.getByText("Explain");
      await userEvent.click(explainButton);

      await waitFor(() => {
        expect(mockPostData).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            query: expect.stringContaining("Explain this code"),
            selected_code: "const x = 5;",
          })
        );
      });
    });

    test("should display selected code in accordion for user messages", () => {
      const messagesWithSelectedCode = [
        {
          id: 1,
          role: "user",
          content: "Explain this code:",
          selected_code: "def example():\n    return True",
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithSelectedCode} setMessages={jest.fn()} />);

      expect(screen.getByText("View highlighted code")).toBeInTheDocument();
    });
  });

  describe("Version Display", () => {
    test("should display version number for messages with code", () => {
      const messagesWithVersion = [
        {
          id: 1,
          role: "assistant",
          content: "Updated code",
          code_snippet: "def versioned():\n    pass",
          version_number: 3,
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithVersion} setMessages={jest.fn()} />);

      const versionElement = screen.getByText("3");
      expect(versionElement).toBeInTheDocument();
    });

    test("should display code icon when no version number", () => {
      const messagesWithoutVersion = [
        {
          id: 1,
          role: "assistant",
          content: "Code without version",
          code_snippet: "def no_version():\n    pass",
          version_number: null,
          timestamp: new Date().toISOString(),
        },
      ];

      render(<ChatPanel {...defaultProps} messages={messagesWithoutVersion} setMessages={jest.fn()} />);

      expect(screen.getByText("</>")).toBeInTheDocument();
    });
  });

  describe("Accessibility", () => {
    test("should have proper ARIA labels and titles", () => {
      render(<ChatPanel {...defaultProps} />);

      expect(screen.getByTitle("Send message")).toBeInTheDocument();
      expect(screen.getByTitle("Close chat panel")).toBeInTheDocument();
      expect(screen.getByTitle("Clear chat")).toBeInTheDocument();
      expect(screen.getByTitle("Select AI model")).toBeInTheDocument();
    });

    test("should focus input on mount", async () => {
      render(<ChatPanel {...defaultProps} />);

      const input = screen.getByPlaceholderText("Ask about your code...");

      await waitFor(() => {
        expect(input).toHaveFocus();
      });
    });
  });
});
