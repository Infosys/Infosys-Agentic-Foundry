import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faUser,
  faRobot,
  faThumbsUp,
  faThumbsDown,
  faRotateRight,
  faChevronDown,
  faChevronUp,
  faTimes,
  faCheckCircle,
  faExclamationTriangle,
  faPaperPlane
} from "@fortawesome/free-solid-svg-icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import rehypeHighlight from 'rehype-highlight';
// import 'highlight.js/styles/github.css'; // Choose your theme
import styles from "./ChatBubble.module.css";
import { BOT, USER } from "../../constant";

const ChatBubble = ({ 
  message, 
  onFeedback, 
  onRegenerate, 
  isGenerating = false,
  onOpenCanvas // <-- add prop
}) => {
  const [showSteps, setShowSteps] = useState(false);
  // Track which feedback is currently highlighted ("up" or "down" or null)
  const [highlightedFeedback, setHighlightedFeedback] = useState(null);
  // Track if feedback input is open for thumbs down
  const [showFeedbackInput, setShowFeedbackInput] = useState(false);
  // Track feedback text for thumbs down
  const [feedbackText, setFeedbackText] = useState("");
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const isBot = message.type === BOT;
  const isUser = message.type === USER;
  const isWelcomeMessage = message.isWelcomeMessage || false;

  const formatTime = (timestamp) => {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
  };

  // Thumbs up click handler
  const handleThumbsUp = () => {
    if (highlightedFeedback === "up") {
      setHighlightedFeedback(null);
      // Do NOT call onFeedback here, just remove highlight
      return;
    }
    setHighlightedFeedback("up");
    setShowFeedbackInput(false);
    setFeedbackText("");
    onFeedback(message.id, null, "positive");
  };

  // Thumbs down click handler
  const handleThumbsDown = () => {
    if (highlightedFeedback === "down") {
      setHighlightedFeedback(null);
      setShowFeedbackInput(false);
      setFeedbackText("");
      // Do NOT call onFeedback here, just remove highlight
      return;
    }
    setShowFeedbackInput(true);
  };

  // Feedback submit for thumbs down
  const handleFeedbackSubmit = () => {
    setHighlightedFeedback("down");
    setShowFeedbackInput(false);
    onFeedback(message.id, feedbackText, "negative");
    setFeedbackText("");
  };

  // Cancel feedback input
  const handleFeedbackCancel = () => {
    setShowFeedbackInput(false);
    setFeedbackText("");
  };

  const getAgentIcon = () => {
    switch (message.agentType) {
      case 'META_AGENT':
        return '🧠';
      case 'MULTI_AGENT':
        return '👥';
      case 'REACT_AGENT':
        return '⚡';
      default:
        return <FontAwesomeIcon icon={faRobot} />;
    }
  };

  function autoGrow(e) {
    const textarea = e.target;
    textarea.style.height = '32px';
    textarea.style.height = Math.min(textarea.scrollHeight, 96) + 'px';
  }

  // Add a CTA button for canvas opening (for demo, only for bot messages with code, chart, etc.)
  const handleOpenCanvasCTA = (type, content) => {
    // Generate a unique id for the canvas (e.g., message id + type)
    const id = `${message.id}-${type}`;
    let canvasContent = content;
    // Remove markdown code fences if type is 'code'
    if (type === 'code' && typeof canvasContent === 'string') {
      canvasContent = canvasContent.replace(/```python[\r\n]+([\s\S]*?)```/i, '$1').replace(/```[\r\n]+([\s\S]*?)```/i, '$1');
    }
    // For quiz, use mock data if content is not a valid quiz object
    if (type === 'quiz') {
      canvasContent = {
        question: "What is the capital of France?",
        options: ["Berlin", "Madrid", "Paris", "Rome"],
        answer: "Paris"
      };
    }
    if (typeof onOpenCanvas === 'function') {
      onOpenCanvas({
        id,
        type,
        content: canvasContent,
        linkedMessageId: message.id,
      });
    }
  };

  return (
    <div className={`${styles.container} ${isUser ? styles.userMessage : styles.botMessage}`}>
      {/* Avatar */}
      <div className={styles.avatarContainer}>
        <div className={`${styles.avatar} ${isUser ? styles.userAvatar : styles.botAvatar}`}>
          {isUser ? (
            <FontAwesomeIcon icon={faUser} className={styles.avatarIcon} />
          ) : (
            <span className={styles.agentIcon}>{getAgentIcon()}</span>
          )}
        </div>
      </div>

      {/* Message Content */}
      <div className={styles.messageWrapper}>
        <div className={`${styles.messageBubble} ${isUser ? styles.userBubble : styles.botBubble}`}>
          {/* Message Content */}
          <div className={styles.messageContent}>
            {isBot ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                rehypePlugins={[rehypeHighlight]}
                components={{
                  p: ({ children }) => <p className={styles.markdownParagraph}>{children}</p>,
                  code({node, inline, className, children, ...props}) {
                    return inline ? (
                      <code className={styles.inlineCode} {...props}>{children}</code>
                    ) : (
                      <pre className={styles.preBlock}>
                        <code className={className ? styles.codeBlock : styles.inlineCode} {...props}>
                          {children}
                        </code>
                      </pre>
                    );
                  },
                  ul: ({ children }) => <ul className={styles.markdownList}>{children}</ul>,
                  ol: ({ children }) => <ol className={styles.markdownList}>{children}</ol>,
                  li: ({ children }) => <li className={styles.markdownListItem}>{children}</li>,
                }}
              >
                {message.content}
              </ReactMarkdown>
            ) : (
              <p className={styles.userText}>{message.content}</p>
            )}
          </div>

          {/* Timestamp */}
          <div className={styles.timestamp}>
            {formatTime(message.timestamp)}
          </div>          {/* STEPS CTA Button - bottom right of bubble */}
          {isBot && message.steps && message.steps.length > 0 && !isWelcomeMessage && (
            <button
              className={styles.stepsCta}
              onClick={() => setShowSteps(!showSteps)}
              aria-label="Show execution steps"
            >
              STEPS <FontAwesomeIcon icon={showSteps ? faChevronUp : faChevronDown} style={{marginLeft: 4}} />
            </button>
          )}
        </div>        {/* Steps Accordion - below the bubble */}
        {isBot && message.steps && message.steps.length > 0 && !isWelcomeMessage && (
          <div
            className={styles.stepsAccordion}
            aria-hidden={!showSteps}
            style={{
              maxHeight: showSteps ? '600px' : '0',
              opacity: showSteps ? 1 : 0,
              pointerEvents: showSteps ? 'auto' : 'none',
              transition: 'max-height 0.22s cubic-bezier(.4,0,.2,1), opacity 0.22s cubic-bezier(.4,0,.2,1)'
            }}
          >
            <div className={styles.stepsHeader}>
              <span>Execution Steps</span>
              {/* <button
                className={styles.stepsCloseBtn}
                onClick={() => setShowSteps(false)}
                aria-label="Close steps"
              >
                <FontAwesomeIcon icon={faTimes} />
              </button> */}
            </div>
            <div className={styles.stepsContent}>
              {message.steps.map((step, index) => (
                <div key={index} className={styles.stepItem}>
                  <div className={styles.stepNumber}>{index + 1}</div>
                  <div className={styles.stepText}>
                    <ReactMarkdown 
                      remarkPlugins={[remarkGfm, remarkBreaks]}
                      rehypePlugins={[rehypeHighlight]}>
                      {step}
                    </ReactMarkdown>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}        {/* Bot-specific features */}
        {isBot && !isWelcomeMessage && (
          <div className={styles.botFeatures}>
            {/* Feedback Section */}
            {!showFeedbackInput && (
              <div className={styles.feedbackWrapper}>
                <button
                  className={`${styles.feedbackButton} ${highlightedFeedback === 'up' ? styles.highlighted : ''}`}
                  onClick={handleThumbsUp}
                  title="Good response"
                >
                  <FontAwesomeIcon icon={faThumbsUp} />
                </button>
                <button
                  className={`${styles.feedbackButton} ${highlightedFeedback === 'down' ? styles.highlighted : ''}`}
                  onClick={handleThumbsDown}
                  title="Poor response"
                >
                  <FontAwesomeIcon icon={faThumbsDown} style={{transform: 'scaleX(-1)'}} />
                </button>
                <button
                  className={styles.feedbackButton}
                  onClick={() => onRegenerate(message.id)}
                  title="Regenerate response"
                >
                  <FontAwesomeIcon
                    icon={faRotateRight}
                    style={{transform: 'rotate(-106deg)'}}
                    className={isGenerating ? styles.spinning : ''}
                  />
                </button>
              </div>
            )}

            {/* Feedback Input */}
            {showFeedbackInput && (
              <div className={styles.feedbackInputContainer}>
                <div className={styles.feedbackHeader}>
                  <span>Sorry the response didn't go well as expected. Please provide your feedback below:</span>
                  <button
                    className={styles.closeButton}
                    onClick={handleFeedbackCancel}
                  >
                    <FontAwesomeIcon icon={faTimes} />
                  </button>
                </div>
                <div className={styles.feedbackInputRow}>
                  <textarea
                    className={styles.feedbackTextarea}
                    value={feedbackText}
                    onChange={(e) => setFeedbackText(e.target.value)}
                    placeholder="Please describe what went wrong..."
                    rows={1}
                    maxrows={4}
                    style={{resize: 'none', minHeight: '32px', maxHeight: '96px'}}
                    onInput={autoGrow}
                  />
                  <button
                    className={styles.sendButton}
                    onClick={handleFeedbackSubmit}
                    disabled={!feedbackText.trim()}
                    title="Send Feedback"
                  >
                    <FontAwesomeIcon icon={faPaperPlane} />
                  </button>
                </div>
              </div>
            )}

            {/* Feedback Submitted */}
            {feedbackSubmitted && (
              <div className={styles.feedbackSubmitted}>
                <FontAwesomeIcon icon={faCheckCircle} className={styles.successIcon} />
                <span>Thank you for your feedback!</span>
              </div>
            )}

            {/* Tools Used */}
            {/* {message.tools && message.tools.length > 0 && (
              <div className={styles.toolsContainer}>
                <span className={styles.toolsLabel}>Tools used:</span>
                <span className={styles.toolsList}>
                  {message.tools.map((tool, index) => (
                    <span key={index} className={styles.toolTag}>
                      {tool}
                    </span>
                  ))}
                </span>
              </div>
            )} */}

            {/* Canvas CTA Demo Buttons (show only for bot messages) */}
            {isBot && (
              <div className={styles.canvasCtaRow}>
                {/* <button onClick={() => handleOpenCanvasCTA('text', message.content)} className={styles.ctaButton}>
                  Open Text Editor
                </button> */}
                {/* <button onClick={() => handleOpenCanvasCTA('code', message.content)} className={styles.ctaButton}>
                  Open Code Runner
                </button> */}
                {/* <button onClick={() => handleOpenCanvasCTA('chart', message.content)} className={styles.ctaButton}>
                  Open Chart
                </button>
                <button onClick={() => handleOpenCanvasCTA('quiz', message.content)} className={styles.ctaButton}>
                  Open Quiz
                </button>
                <button onClick={() => handleOpenCanvasCTA('markdown', message.content)} className={styles.ctaButton}>
                  Open Markdown
                </button>
                <button onClick={() => handleOpenCanvasCTA('prototype', message.content)} className={styles.ctaButton}>
                  Open Prototype
                </button> */}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatBubble;
