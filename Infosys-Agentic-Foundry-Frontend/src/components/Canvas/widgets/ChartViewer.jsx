import React, { useState, useMemo } from "react";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import styles from "./ChartViewer.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

const ChartViewer = ({ content, messageId, chartType = "auto" }) => {
  const [currentChartType, setCurrentChartType] = useState(chartType);
  const [downloadSuccess, setDownloadSuccess] = useState(false);

  // Color palette for charts
  const COLORS = [
    "#007acc", "#00d4aa", "#ff6b6b", "#4ecdc4", "#45b7d1",
    "#96ceb4", "#ffeaa7", "#dda0dd", "#98d8c8", "#f7dc6f"
  ];

  // Parse and process chart data
  const processedData = useMemo(() => {
    try {
      let data = content;
      
      // Handle new parts chart format with chart_data, labels, and datasets
      if (typeof content === "object" && content.chart_data) {
        const { chart_data } = content;
        
        if (chart_data.labels && chart_data.datasets && Array.isArray(chart_data.datasets)) {
          // Convert datasets format to chart-friendly format
          const transformedData = chart_data.labels.map((label, index) => {
            const dataPoint = { label: label };
            chart_data.datasets.forEach(dataset => {
              if (dataset.data && dataset.data[index] !== undefined) {
                dataPoint[dataset.label] = dataset.data[index];
              }
            });
            return dataPoint;
          });
          return transformedData;
        }
      }
      
      // Handle direct data field (existing parts format)
      if (typeof content === "object" && content.data && Array.isArray(content.data)) {
        data = content.data;
      }
      
      // Handle string content (JSON)
      if (typeof content === "string") {
        try {
          data = JSON.parse(content);
        } catch (e) {
          // If not JSON, try to parse as CSV-like format
          const lines = content.trim().split("\n");
          if (lines.length > 1) {
            const headers = lines[0].split(",").map(h => h.trim());
            data = lines.slice(1).map(line => {
              const values = line.split(",").map(v => v.trim());
              const row = {};
              headers.forEach((header, index) => {
                const value = values[index];
                // Try to convert to number if possible
                row[header] = isNaN(value) ? value : parseFloat(value);
              });
              return row;
            });
          } else {
            return [];
          }
        }
      }

      // Handle array of objects (most common format)
      if (Array.isArray(data)) {
        return data.map(item => {
          if (typeof item === "object" && item !== null) {
            return item;
          }
          return { value: item, name: `Item ${data.indexOf(item) + 1}` };
        });
      }

      // Handle object format (convert to array)
      if (typeof data === "object" && data !== null) {
        if (data.chartData) {
          return Array.isArray(data.chartData) ? data.chartData : [];
        }
        if (data.data) {
          return Array.isArray(data.data) ? data.data : [];
        }
        
        // Convert object to array format
        return Object.entries(data).map(([key, value]) => ({
          name: key,
          value: typeof value === "number" ? value : parseFloat(value) || 0
        }));
      }
      return [];
    } catch (error) {
      console.error("Error processing chart data:", error);
      return [];
    }
  }, [content]);

  // Auto-detect chart type based on data structure
  const detectedChartType = useMemo(() => {
    if (currentChartType !== "auto") return currentChartType;
    
    if (processedData.length === 0) return "bar";
    
    const firstItem = processedData[0];
    const keys = Object.keys(firstItem);
    
    // If we have name/value structure, suggest pie chart
    if (keys.includes("name") && keys.includes("value") && keys.length <= 3) {
      return "pie";
    }
    
    // If we have time-series data (date/time field), suggest line chart
    const hasTimeField = keys.some(key => 
      key.toLowerCase().includes("date") || 
      key.toLowerCase().includes("time") ||
      key.toLowerCase().includes("month") ||
      key.toLowerCase().includes("year")
    );
    if (hasTimeField) return "line";
    
    // If we have multiple numeric fields, suggest area chart
    const numericFields = keys.filter(key => 
      typeof firstItem[key] === "number" && key !== "name"
    );
    if (numericFields.length > 1) return "area";
    
    // Default to bar chart
    return "bar";
  }, [processedData, currentChartType]);

  // Handle chart download
  const handleDownload = () => {
    try {
      const dataStr = JSON.stringify(processedData, null, 2);
      const dataBlob = new Blob([dataStr], { type: "application/json" });
      const url = URL.createObjectURL(dataBlob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `chart-data-${messageId || Date.now()}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      
      setDownloadSuccess(true);
      setTimeout(() => setDownloadSuccess(false), 2000);
    } catch (error) {
      console.error("Download failed:", error);
    }
  };

  // Render different chart types
  const renderChart = () => {
    if (processedData.length === 0) {
      return (
        <div className={styles.emptyState}>
          <SVGIcons icon="fa-chart-bar" width={32} height={32} fill="#cbd5e1" />
          <p className={styles.emptyMessage}>No chart data to display</p>
        </div>
      );
    }

    const chartProps = {
      data: processedData,
      margin: { top: 20, right: 30, left: 20, bottom: 20 }
    };

    switch (detectedChartType) {
      case "line":
        const lineDataKeys = Object.keys(processedData[0]).filter(key => 
          typeof processedData[0][key] === "number"
        );
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis 
                dataKey={Object.keys(processedData[0])[0]} 
                stroke="#64748b"
                fontSize={12}
              />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip 
                contentStyle={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: "6px",
                  fontSize: "12px"
                }}
              />
              <Legend />
              {lineDataKeys.map((key, index) => (
                <Line
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stroke={COLORS[index % COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        );

      case "area":
        const areaDataKeys = Object.keys(processedData[0]).filter(key => 
          typeof processedData[0][key] === "number"
        );
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis 
                dataKey={Object.keys(processedData[0])[0]} 
                stroke="#64748b"
                fontSize={12}
              />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip 
                contentStyle={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: "6px",
                  fontSize: "12px"
                }}
              />
              <Legend />
              {areaDataKeys.map((key, index) => (
                <Area
                  key={key}
                  type="monotone"
                  dataKey={key}
                  stackId="1"
                  stroke={COLORS[index % COLORS.length]}
                  fill={COLORS[index % COLORS.length]}
                  fillOpacity={0.6}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        );

      case "pie":
        const pieDataKey = processedData[0].value !== undefined ? "value" : 
          Object.keys(processedData[0]).find(key => typeof processedData[0][key] === "number");
        
        return (
          <ResponsiveContainer width="100%" height={400}>
            <PieChart>
              <Pie
                data={processedData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                outerRadius={120}
                fill="#8884d8"
                dataKey={pieDataKey || "value"}
              >
                {processedData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: "6px",
                  fontSize: "12px"
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        );

      case "scatter":
        const xKey = Object.keys(processedData[0])[0];
        const yKey = Object.keys(processedData[0]).find(key => 
          key !== xKey && typeof processedData[0][key] === "number"
        );
        
        return (
          <ResponsiveContainer width="100%" height={400}>
            <ScatterChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis 
                dataKey={xKey} 
                stroke="#64748b"
                fontSize={12}
              />
              <YAxis 
                dataKey={yKey} 
                stroke="#64748b" 
                fontSize={12}
              />
              <Tooltip 
                contentStyle={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: "6px",
                  fontSize: "12px"
                }}
              />
              <Scatter 
                data={processedData} 
                fill={COLORS[0]}
              />
            </ScatterChart>
          </ResponsiveContainer>
        );

      case "bar":
      default:
        const barDataKeys = Object.keys(processedData[0]).filter(key => 
          typeof processedData[0][key] === "number"
        );
        
        return (
          <ResponsiveContainer width="100%" height={400}>
            <BarChart {...chartProps}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis 
                dataKey={Object.keys(processedData[0])[0]} 
                stroke="#64748b"
                fontSize={12}
              />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip 
                contentStyle={{
                  backgroundColor: "#ffffff",
                  border: "1px solid #e2e8f0",
                  borderRadius: "6px",
                  fontSize: "12px"
                }}
              />
              <Legend />
              {barDataKeys.map((key, index) => (
                <Bar
                  key={key}
                  dataKey={key}
                  fill={COLORS[index % COLORS.length]}
                  radius={[2, 2, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        );
    }
  };

  const availableChartTypes = [
    { type: "auto", label: "Auto", icon: "fa-magic" },
    { type: "bar", label: "Bar", icon: "fa-chart-column" },
    { type: "line", label: "Line", icon: "fa-chart-line" },
    { type: "area", label: "Area", icon: "fa-chart-area" },
    { type: "pie", label: "Pie", icon: "fa-chart-pie" },
    { type: "scatter", label: "Scatter", icon: "fa-braille" }
  ];

  return (
    <div className={styles.chartViewer}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <div className={styles.contentTag}>
            <SVGIcons icon="fa-chart-bar" width={14} height={14} fill="#007acc" />
            <span>Chart</span>
          </div>
          <div className={styles.chartTypeSelector}>
            {availableChartTypes.map(({ type, label, icon }) => (
              <button
                key={type}
                className={`${styles.chartTypeButton} ${
                  (type === "auto" ? detectedChartType : type) === detectedChartType 
                    ? styles.active 
                    : ""
                }`}
                onClick={() => setCurrentChartType(type)}
                title={`${label} Chart`}
              >
                <SVGIcons icon={icon} width={12} height={12} fill="#666" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>
        
        <div className={styles.toolbarActions}>
          <button
            className={`${styles.toolbarButton} ${downloadSuccess ? styles.success : ""}`}
            onClick={handleDownload}
            title="Download chart data"
          >
            {downloadSuccess ? (
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
                <path d="M16 6L8.5 14.5L4 10" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            ) : (
              <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
                <path d="M10 13V3M7 10L10 13L13 10M5 17H15" 
                  stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Chart Content */}
      <div className={styles.chartContent}>
        {renderChart()}
      </div>

      {/* Footer with data info */}
      <div className={styles.footer}>
        <div className={styles.stats}>
          <span className={styles.stat}>
            Data Points: {processedData.length}
          </span>
          <span className={styles.stat}>
            Chart Type: {detectedChartType.charAt(0).toUpperCase() + detectedChartType.slice(1)}
          </span>
        </div>
      </div>
    </div>
  );
};

export default ChartViewer;
