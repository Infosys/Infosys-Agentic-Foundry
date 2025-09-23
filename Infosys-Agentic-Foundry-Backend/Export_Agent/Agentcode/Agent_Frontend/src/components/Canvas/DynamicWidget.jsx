import React from 'react';
import CodeViewer from './widgets/CodeViewer';
import TextViewer from './widgets/TextViewer';
import TableViewer from './widgets/TableViewer';
import FormViewer from './widgets/FormViewer';

// Widget mapping for dynamic rendering
const widgetMap = {
  code: CodeViewer,
  text: TextViewer,
  table: TableViewer,
  form: FormViewer,
  // Add more widget types as needed
};

const DynamicWidget = ({ type, content, messageId, ...props }) => {
  const Widget = widgetMap[type];
  
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
  
  return (
    <Widget 
      content={content}
      messageId={messageId}
      {...props}
    />
  );
};

export default DynamicWidget;
