import React from 'react';
import CodeViewer from './widgets/CodeViewer';
import PlanCard from './widgets/PlanCard';
import planCardStyles from './widgets/PlanCard.module.css';
import TextViewer from './widgets/TextViewer';
import TableViewer from './widgets/TableViewer';
import FormViewer from './widgets/FormViewer';
import ChartViewer from './widgets/ChartViewer';
import ImageViewer from './widgets/ImageViewer';
import PartsRenderer from './PartsRenderer';
import EmailViewer from './widgets/EmailViewer';

// Widget mapping for dynamic rendering
const widgetMap = {
  code: CodeViewer,
  text: TextViewer,
  canvas_text: TextViewer, // Alias for text viewer
  table: TableViewer,
  form: FormViewer,
  chart: ChartViewer,
  graph: ChartViewer, // Alias for chart
  visualization: ChartViewer, // Alias for chart
  image: ImageViewer,
  img: ImageViewer, // Alias for image
  picture: ImageViewer, // Alias for image
  photo: ImageViewer, // Alias for image
  parts: PartsRenderer, // New parts renderer
  json: CodeViewer, // default JSON viewer (will override below)
  email: EmailViewer, // Email viewer for email content
  // Add more widget types as needed
};

const DynamicWidget = ({ type, content, messageId,
  is_last,
  sendUserMessage,
  ...props
}) => {
  // Special handling for parts type
  if (type === 'parts') {
    return (
      <PartsRenderer 
        parts={content}
        messageId={messageId}
        sendUserMessage={sendUserMessage}
        {...props}
      />
    );
  }

  // For json type, check if content is card object, selected agent, or array
  if (type === 'json') {
    // If content is an object and keys look like 'card_1', 'card_2', or selectedAgent is 'Sunrise Agent', render PlanCard for each
  const isCardObject = content && typeof content === 'object' && !Array.isArray(content) && Object.keys(content).some((k) => k.toLowerCase().startsWith('card_'));
  const isSunriseAgent = typeof props.selectedAgent === 'string' && props.selectedAgent.toLowerCase().startsWith('sunrise');
    if (isCardObject || isSunriseAgent) {
      const { isMinimized, isFullscreen } = props;
      let cardListClass = '';
      if (isMinimized) cardListClass = planCardStyles.cardListMinimized;
      else if (isFullscreen) cardListClass = planCardStyles.cardListFullscreen;
      else cardListClass = planCardStyles.cardListDefault;
      // // If content is not a card object, wrap it in an array for rendering
      const cards = isCardObject ? Object.values(content) : [content];
      return (
        <div className={cardListClass}>
          {cards.map((card, idx) => (
            <PlanCard key={idx} content={card} sendUserMessage={sendUserMessage} />
          ))}
        </div>
      );
    }
    // If content.data is array, render CodeViewer
    if (
      content &&
      typeof content === 'object' &&
      Array.isArray(content.data)
    ) {
      return <CodeViewer content={content.data} {...props} />;
    }
    // Otherwise, fallback to CodeViewer
    return <CodeViewer content={content} {...props} />;
  }

  // Helper function to safely stringify content
  const safeStringifyContent = (content) => {
    if (typeof content === 'string') return content;
    if (content === null || content === undefined) return '';
    if (typeof content === 'object') {
      try {
        return JSON.stringify(content, null, 2);
      } catch (error) {
        return String(content);
      }
    }
    return String(content);
  };

  const Widget = widgetMap[type];
  if (!Widget) {
    // Fallback to text viewer for unknown types
    const FallbackWidget = widgetMap.text;
    return FallbackWidget ? (
      <FallbackWidget 
        content={safeStringifyContent(content)}
        messageId={messageId}
        {...props}
      />
    ) : (
      <div style={{ padding: '20px', textAlign: 'center', color: '#64748b' }}>
        Unsupported content type: {type}
      </div>
    );
  }

  // For email type, pass is_last from content to EmailViewer
  if (type === 'email') {
    return (
      <Widget
        content={content}
        messageId={messageId}
        is_last={is_last}
        sendUserMessage={sendUserMessage}
      />
    );
  }
  return (
    <Widget 
      content={content}
      messageId={messageId}
      {...props}
    />
  );
};

export default DynamicWidget;
