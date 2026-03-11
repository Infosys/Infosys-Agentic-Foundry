import grafanaIcon from "../Assets/grafana-icon.png";
import postgresqlIcon from "../Assets/postgresql-icon.png";

// All available icon names - auto-maintained list for IconShowcase
export const ICON_NAMES = [
  "menu",
  "hamburger",
  "fa-solid fa-user-xmark",
  "fa-solid fa-pen",
  "pencil",
  "disable_icon",
  "ionic-ios-send",
  "hardware-chip",
  "person-circle",
  "close-icon",
  "x",
  "fa-user-plus",
  "fa-user-check",
  "fa-screwdriver-wrench",
  "fa-robot",
  "nav-chat",
  "new-chat",
  "vault-lock",
  "search",
  "fa-question",
  "fa-user",
  "slider-rect",
  "fa-plus",
  "fa-minus",
  "fa-trash",
  "trash",
  "recycle-bin",
  "fa-xmark",
  "fa-circle-xmark",
  "caret",
  "downarrow",
  "rightarrow",
  "arrow-right",
  "info",
  "exclamation",
  "check",
  "download",
  "drop_arrow_down",
  "drop_arrow_up",
  "file",
  "detail",
  "fa-regular fa-copy",
  "eyeIcon",
  "eye",
  "eye-slash",
  "metrics",
  "warnings",
  "tableIcon",
  "accordionIcon",
  "fa-solid fa-up-right-and-down-left-from-center",
  "ground-truth",
  "data-connectors",
  "server",
  "database",
  "postgresql",
  "mysql",
  "mongodb",
  "sqlite",
  "close",
  "plug",
  "play",
  "settings",
  "clipboard-check",
  "fa-chart-bar",
  "fa-chart-line",
  "fa-chart-area",
  "fa-chart-pie",
  "fa-chart-column",
  "fa-braille",
  "fa-magic",
  "fa-image",
  "fa-exclamation-triangle",
  "thermometerIcon",
  "save",
  "update",
  "grafana",
  "upload-old",
  "upload-new",
  "layout-grid",
  "list",
  "refresh",
  "refresh-new",
  "info-modern",
  "message-square",
  "plus",
  "wrench",
  "eye2",
  "chevronRight",
  "fileText",
  "folder",
  "lucide-play",
  "mic",
  "sparkles",
  "send",
  "brain",
  "bolt",
  "circle-check",
  "activity",
  "messages-square",
  "thermometer",
  "sliders-vertical",
  "circle-plus",
  "trash-2",
  "thumbs-up",
  "thumbs-down",
  "rotate-ccw",
  "chevron-down",
  "chevron-left",
  "chevron-right",
  "checkbox-checked",
  "close-x",
  "checkmark-circle",
  "checkmark",
  "circle-check-big",
  "funnel",
  "folder-blue",
  "file-pdf",
  "file-csv",
  "file-image",
  "file-default",
  "download-file",
  "selection-options",
  "upload",
  "at-sign",
  "send-message",
  "stop-recording",
  "knowledge-base",
  "search-knowledge",
  "history",
  "filter-funnel",
  "chat-bubble",
  "trash-outline",
  "plan-header-icon",
  "thumbs-up-2",
  "thumbs-down-2",
  "step-completed",
  "step-spinner",
  "close-small",
  "history-clock",
  "star-outline",
  "activity-pulse",
  "download-arrow",
  "check-success",
  "copy",
  "canvas-grid",
  "fullscreen-expand",
  "fullscreen-collapse",
  "close-canvas",
  "step-checkmark",
  "execution-steps",
  "chevron-down-sm",
  "view-details-eye",
  "light-icon",
  "dark-icon",
  "logout",
  "fa-project-diagram",
  "fa-user-outline",
];

const SVGIcons = (props) => {
  const { icon, width = 20, height = 20, fill = "currentColor", color = "currentColor", stroke } = props;
  const svgStyle = {
    width,
    height,
    fill,
    color,
    stroke: stroke || "currentColor",
  };
  switch (icon) {
    case "menu":
    case "hamburger":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" style={{ width, height }}>
          <path d="M2.5 5H17.5" stroke={stroke || "currentColor"} strokeWidth="1.67" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M2.5 10H17.5" stroke={stroke || "currentColor"} strokeWidth="1.67" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M2.5 15H17.5" stroke={stroke || "currentColor"} strokeWidth="1.67" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "fa-solid fa-user-xmark":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 512" {...svgStyle}>
          <path d="M96 128a128 128 0 1 1 256 0A128 128 0 1 1 96 128zM0 482.3C0 383.8 79.8 304 178.3 304l91.4 0C368.2 304 448 383.8 448 482.3c0 16.4-13.3 29.7-29.7 29.7L29.7 512C13.3 512 0 498.7 0 482.3zM471 143c9.4-9.4 24.6-9.4 33.9 0l47 47 47-47c9.4-9.4 24.6-9.4 33.9 0s9.4 24.6 0 33.9l-47 47 47 47c9.4 9.4 9.4 24.6 0 33.9s-24.6 9.4-33.9 0l-47-47-47 47c-9.4 9.4-24.6 9.4-33.9 0s-9.4-24.6 0-33.9l47-47-47-47c-9.4-9.4-9.4-24.6 0-33.9z" />
        </svg>
      );
    case "fa-solid fa-pen":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {...svgStyle} fill="none">
          <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "pencil":
      return (
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
          <g>
            <path
              d="M15.2 3.8c.5-.5 1.3-.5 1.8 0l.2.2c.5.5.5 1.3 0 1.8l-9.7 9.7-2.7.3.3-2.7 9.7-9.7z"
              fill="currentColor"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <rect x="2.5" y="14.5" width="5" height="2" rx="0.8" fill="currentColor" opacity="0.18" />
            <path d="M13.7 5.7l1.6 1.6" stroke="#fff" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          </g>
        </svg>
      );
    case "disable_icon":
      return (
        <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
          <g>
            <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <line x1="4.50" y1="15.10" x2="15.10" y2="4.50" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </g>
        </svg>
      );
    case "ionic-ios-send":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" className="ionicon" viewBox="0 0 512 512" {...svgStyle}>
          <path d="M476.59 227.05l-.16-.07L49.35 49.84A23.56 23.56 0 0027.14 52 24.65 24.65 0 0016 72.59v113.29a24 24 0 0019.52 23.57l232.93 43.07a4 4 0 010 7.86L35.53 303.45A24 24 0 0016 327v113.31A23.57 23.57 0 0026.59 460a23.94 23.94 0 0013.22 4 24.55 24.55 0 009.52-1.93L476.4 285.94l.19-.09a32 32 0 000-58.8z" />
        </svg>
      );
    case "hardware-chip":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" className="ionicon" viewBox="0 0 512 512" {...svgStyle}>
          <path
            d="M352 128H160a32 32 0 00-32 32v192a32 32 0 0032 32h192a32 32 0 0032-32V160a32 32 0 00-32-32zm0 216a8 8 0 01-8 8H168a8 8 0 01-8-8V168a8 8 0 018-8h176a8 8 0 018 8z"
            fill="none"
          />
          <rect x="160" y="160" width="192" height="192" rx="8" ry="8" />
          <path d="M464 192a16 16 0 000-32h-16v-32a64.07 64.07 0 00-64-64h-32V48a16 16 0 00-32 0v16h-48V48a16 16 0 00-32 0v16h-48V48a16 16 0 00-32 0v16h-32a64.07 64.07 0 00-64 64v32H48a16 16 0 000 32h16v48H48a16 16 0 000 32h16v48H48a16 16 0 000 32h16v32a64.07 64.07 0 0064 64h32v16a16 16 0 0032 0v-16h48v16a16 16 0 0032 0v-16h48v16a16 16 0 0032 0v-16h32a64.07 64.07 0 0064-64v-32h16a16 16 0 000-32h-16v-48h16a16 16 0 000-32h-16v-48zm-80 160a32 32 0 01-32 32H160a32 32 0 01-32-32V160a32 32 0 0132-32h192a32 32 0 0132 32z" />
        </svg>
      );
    case "person-circle":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.33333" />
          <circle cx="8" cy="6" r="2" stroke="currentColor" strokeWidth="1.33333" />
          <path d="M4 12.5C4.5 10.5 6 9.5 8 9.5C10 9.5 11.5 10.5 12 12.5" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" />
        </svg>
      );
    case "close-icon":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" className="ionicon" viewBox="0 0 512 512" {...svgStyle}>
          <path fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="32" d="M368 368L144 144M368 144L144 368" />
        </svg>
      );
    case "x":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height, color, fill, stroke }}>
          <path d="M18 6 6 18"></path>
          <path d="m6 6 12 12"></path>
        </svg>
      );
    case "fa-user-plus":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 512" {...svgStyle}>
          <path d="M96 128a128 128 0 1 1 256 0A128 128 0 1 1 96 128zM0 482.3C0 383.8 79.8 304 178.3 304l91.4 0C368.2 304 448 383.8 448 482.3c0 16.4-13.3 29.7-29.7 29.7L29.7 512C13.3 512 0 498.7 0 482.3zM504 312l0-64-64 0c-13.3 0-24-10.7-24-24s10.7-24 24-24l64 0 0-64c0-13.3 10.7-24 24-24s24 10.7 24 24l0 64 64 0c13.3 0 24 10.7 24 24s-10.7 24-24 24l-64 0 0 64c0 13.3-10.7 24-24 24s-24-10.7-24-24z" />
        </svg>
      );
    case "fa-user-check":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 512" {...svgStyle}>
          <path d="M96 128a128 128 0 1 1 256 0A128 128 0 1 1 96 128zM0 482.3C0 383.8 79.8 304 178.3 304l91.4 0C368.2 304 448 383.8 448 482.3c0 16.4-13.3 29.7-29.7 29.7L29.7 512C13.3 512 0 498.7 0 482.3zM625 177L497 305c-9.4 9.4-24.6 9.4-33.9 0l-64-64c-9.4-9.4-9.4-24.6 0-33.9s24.6-9.4 33.9 0l47 47L591 143c9.4-9.4 24.6-9.4 33.9 0s9.4 24.6 0 33.9z" />
        </svg>
      );
    case "fa-screwdriver-wrench":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" style={{ width, height, color }}>
          <path
            d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "fa-robot":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <path d="M8.00016 5.33334V2.66667H5.3335" stroke={stroke || color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path
            d="M11.9998 5.33333H3.99984C3.26346 5.33333 2.6665 5.93028 2.6665 6.66666V12C2.6665 12.7364 3.26346 13.3333 3.99984 13.3333H11.9998C12.7362 13.3333 13.3332 12.7364 13.3332 12V6.66666C13.3332 5.93028 12.7362 5.33333 11.9998 5.33333Z"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M1.3335 9.33333H2.66683" stroke={stroke || color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M13.3335 9.33333H14.6668" stroke={stroke || color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M10 8.66667V10" stroke={stroke || color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M6 8.66667V10" stroke={stroke || color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "nav-chat":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <path
            d="M14.6668 11.3333C14.6668 11.687 14.5264 12.0261 14.2763 12.2761C14.0263 12.5262 13.6871 12.6667 13.3335 12.6667H4.55216C4.19857 12.6667 3.85949 12.8073 3.6095 13.0573L2.1415 14.5253C2.0753 14.5915 1.99097 14.6366 1.89916 14.6548C1.80735 14.6731 1.71218 14.6637 1.6257 14.6279C1.53922 14.5921 1.4653 14.5314 1.41329 14.4536C1.36128 14.3758 1.33351 14.2843 1.3335 14.1907V3.33333C1.3335 2.97971 1.47397 2.64057 1.72402 2.39052C1.97407 2.14048 2.31321 2 2.66683 2H13.3335C13.6871 2 14.0263 2.14048 14.2763 2.39052C14.5264 2.64057 14.6668 2.97971 14.6668 3.33333V11.3333Z"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "new-chat":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="800px" height="800px" viewBox="0 0 24 24" {...svgStyle}>
          <path d="M12 2C6.48 2 2 5.58 2 10c0 2.39 1.39 4.53 3.54 6.03-.34 1.23-1.03 2.3-1.99 3.17-.2.18-.25.46-.13.7.12.24.37.38.63.38 1.52 0 3.04-.58 4.38-1.64C10.07 19.68 11.02 20 12 20c5.52 0 10-3.58 10-8s-4.48-8-10-8zm0 14c-.98 0-1.93-.32-2.74-.88-.2-.14-.47-.13-.66.02-1.06.84-2.3 1.34-3.6 1.47.56-.72.99-1.54 1.27-2.42.08-.26-.02-.54-.24-.7C4.4 12.9 3.5 11.5 3.5 10c0-3.31 3.58-6 8-6s8 2.69 8 6-3.58 6-8 6z" />
        </svg>
      );
    case "vault-lock":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <path
            d="M12.6667 7.33334H3.33333C2.59695 7.33334 2 7.9303 2 8.66668V13.3333C2 14.0697 2.59695 14.6667 3.33333 14.6667H12.6667C13.403 14.6667 14 14.0697 14 13.3333V8.66668C14 7.9303 13.403 7.33334 12.6667 7.33334Z"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M4.6665 7.33334V4.66668C4.6665 3.78262 5.01769 2.93478 5.64281 2.30965C6.26794 1.68453 7.11578 1.33334 7.99984 1.33334C8.88389 1.33334 9.73174 1.68453 10.3569 2.30965C10.982 2.93478 11.3332 3.78262 11.3332 4.66668V7.33334"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "search":
      // Modern search icon: circle with centered magnifier, thick stroke
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          width={width}
          height={height}
          fill="none"
          stroke={color || fill || "#343741"}
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={svgStyle}>
          <circle cx="11" cy="11" r="7" fill="none" />
          <line x1="16.5" y1="16.5" x2="21" y2="21" />
        </svg>
      );
    case "fa-question":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 512" {...svgStyle}>
          <path d="M80 160c0-35.3 28.7-64 64-64l32 0c35.3 0 64 28.7 64 64l0 3.6c0 21.8-11.1 42.1-29.4 53.8l-42.2 27.1c-25.2 16.2-40.4 44.1-40.4 74l0 1.4c0 17.7 14.3 32 32 32s32-14.3 32-32l0-1.4c0-8.2 4.2-15.8 11-20.2l42.2-27.1c36.6-23.6 58.8-64.1 58.8-107.7l0-3.6c0-70.7-57.3-128-128-128l-32 0C73.3 32 16 89.3 16 160c0 17.7 14.3 32 32 32s32-14.3 32-32zm80 320a40 40 0 1 0 0-80 40 40 0 1 0 0 80z" />
        </svg>
      );
    case "fa-user":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512" {...svgStyle}>
          <path d="M224 256A128 128 0 1 0 224 0a128 128 0 1 0 0 256zm-45.7 48C79.8 304 0 383.8 0 482.3C0 498.7 13.3 512 29.7 512l388.6 0c16.4 0 29.7-13.3 29.7-29.7C448 383.8 368.2 304 269.7 304l-91.4 0z" />
        </svg>
      );
    case "fa-user-outline":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512" {...svgStyle}>
          <path fill="currentColor" d="M224 48a80 80 0 1 1 0 160 80 80 0 1 1 0-160zm0 208A128 128 0 1 0 224 0a128 128 0 1 0 0 256zm-45.7 96h.3c18.9 0 37.5-4.2 54.7-12.4c1.3-.6 2.6-1.3 3.9-1.9c-22.7-13.3-39.3-36.1-44.4-63.1l-.8-4.6H178.3c-57.5 0-105.1 43.3-111.5 99l88.2 0c.8-8.4 7.8-15 16.6-15h6.7zm91.4 0h6.7c8.8 0 15.8 6.6 16.6 15h88.2c-6.4-55.7-54-99-111.5-99H255.9l-.8 4.6c-5.1 27-21.7 49.7-44.4 63.1c1.3 .7 2.6 1.3 3.9 1.9c17.2 8.2 35.7 12.4 54.7 12.4h.3zM29.7 416c-16.4 0-29.7-13.3-29.7-29.7C0 323.8 79.8 256 178.3 256h91.4C368.2 256 448 323.8 448 386.3c0 16.4-13.3 29.7-29.7 29.7H29.7z"/>
        </svg>
      );
    case "slider-rect":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" {...svgStyle}>
          <path d="M0 416c0 17.7 14.3 32 32 32l54.7 0c12.3 28.3 40.5 48 73.3 48s61-19.7 73.3-48L480 448c17.7 0 32-14.3 32-32s-14.3-32-32-32l-246.7 0c-12.3-28.3-40.5-48-73.3-48s-61 19.7-73.3 48L32 384c-17.7 0-32 14.3-32 32zm128 0a32 32 0 1 1 64 0 32 32 0 1 1 -64 0zM320 256a32 32 0 1 1 64 0 32 32 0 1 1 -64 0zm32-80c-32.8 0-61 19.7-73.3 48L32 224c-17.7 0-32 14.3-32 32s14.3 32 32 32l246.7 0c12.3 28.3 40.5 48 73.3 48s61-19.7 73.3-48l54.7 0c17.7 0 32-14.3 32-32s-14.3-32-32-32l-54.7 0c-12.3-28.3-40.5-48-73.3-48zM192 128a32 32 0 1 1 0-64 32 32 0 1 1 0 64zm73.3-64C253 35.7 224.8 16 192 16s-61 19.7-73.3 48L32 64C14.3 64 0 78.3 0 96s14.3 32 32 32l86.7 0c12.3 28.3 40.5 48 73.3 48s61-19.7 73.3-48L480 128c17.7 0 32-14.3 32-32s-14.3-32-32-32L265.3 64z" />
        </svg>
      );
    case "fa-plus":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M3.3335 8H12.6668" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M8 3.33333V12.6667" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "fa-minus":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M3.3335 8H12.6668" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "fa-trash":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512" {...svgStyle}>
          <path d="M135.2 17.7L128 32 32 32C14.3 32 0 46.3 0 64S14.3 96 32 96l384 0c17.7 0 32-14.3 32-32s-14.3-32-32-32l-96 0-7.2-14.3C307.4 6.8 296.3 0 284.2 0L163.8 0c-12.1 0-23.2 6.8-28.6 17.7zM416 128L32 128 53.2 467c1.6 25.3 22.6 45 47.9 45l245.8 0c25.3 0 46.3-19.7 47.9-45L416 128z" />
        </svg>
      );
    case "trash":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M10 11v6"></path>
          <path d="M14 11v6"></path>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path>
          <path d="M3 6h18"></path>
          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
      );
    case "recycle-bin":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {...svgStyle} fill="none">
          <path d="M3 6h18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <path d="M10 11v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <path d="M14 11v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "fa-xmark":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" {...svgStyle}>
          <path d="M342.6 150.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L192 210.7 86.6 105.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3L146.7 256 41.4 361.4c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L192 301.3 297.4 406.6c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L237.3 256 342.6 150.6z" />
        </svg>
      );
    case "fa-circle-xmark":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" {...svgStyle}>
          <path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512zM175 175c9.4-9.4 24.6-9.4 33.9 0l47 47 47-47c9.4-9.4 24.6-9.4 33.9 0s9.4 24.6 0 33.9l-47 47 47 47c9.4 9.4 9.4 24.6 0 33.9s-24.6 9.4-33.9 0l-47-47-47 47c-9.4 9.4-24.6 9.4-33.9 0s-9.4-24.6 0-33.9l47-47-47-47c-9.4-9.4-9.4-24.6 0-33.9z" />
        </svg>
      );
    case "caret":
      return (
        <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" {...svgStyle}>
          <path d="M16.59 8.59L12 13.17 7.41 8.59 6 10l6 6 6-6-1.41-1.41z"></path>
        </svg>
      );
    case "downarrow":
      return (
        <svg {...svgStyle} viewBox="0 -6 524 524" xmlns="http://www.w3.org/2000/svg">
          <title>down</title>
          <path d="M64 191L98 157 262 320 426 157 460 191 262 387 64 191Z" />
        </svg>
      );
    case "rightarrow":
      return (
        <svg {...svgStyle} viewBox="-77 0 512 512" xmlns="http://www.w3.org/2000/svg">
          <title>right</title>
          <path d="M98 460L64 426 227 262 64 98 98 64 294 262 98 460Z" />
        </svg>
      );
    case "arrow-right":
      return (
        <svg width={width} height={height} viewBox="0 0 12 10" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M0.987305 5H10.6543" stroke={stroke} strokeWidth="1.67" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M6.82031 1L10.6543 5L6.82031 9" stroke={stroke} strokeWidth="1.67" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "info":
      return (
        <svg {...svgStyle} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 512">
          <path d="M48 80a48 48 0 1 1 96 0A48 48 0 1 1 48 80zM0 224c0-17.7 14.3-32 32-32l64 0c17.7 0 32 14.3 32 32l0 224 32 0c17.7 0 32 14.3 32 32s-14.3 32-32 32L32 512c-17.7 0-32-14.3-32-32s14.3-32 32-32l32 0 0-192-32 0c-17.7 0-32-14.3-32-32z" />
        </svg>
      );
    case "exclamation":
      return (
        <svg {...svgStyle} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 512">
          <path d="M96 64c0-17.7-14.3-32-32-32S32 46.3 32 64l0 256c0 17.7 14.3 32 32 32s32-14.3 32-32L96 64zM64 480a40 40 0 1 0 0-80 40 40 0 1 0 0 80z" />
        </svg>
      );
    case "check":
      return (
        <svg {...svgStyle} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512">
          <path d="M438.6 105.4c12.5 12.5 12.5 32.8 0 45.3l-256 256c-12.5 12.5-32.8 12.5-45.3 0l-128-128c-12.5-12.5-12.5-32.8 0-45.3s32.8-12.5 45.3 0L160 338.7 393.4 105.4c12.5-12.5 32.8-12.5 45.3 0z" />
        </svg>
      );
    case "download":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <title>down</title>
          <path d="M12 2C12.5523 2 13 2.44772 13 3V15.5858L16.2929 12.2929C16.6834 11.9024 17.3166 11.9024 17.7071 12.2929C18.0976 12.6834 18.0976 13.3166 17.7071 13.7071L12.7071 18.7071C12.3166 19.0976 11.6834 19.0976 11.2929 18.7071L6.29289 13.7071C5.90237 13.3166 5.90237 12.6834 6.29289 12.2929C6.68342 11.9024 7.31658 11.9024 7.70711 12.2929L11 15.5858V3C11 2.44772 11.4477 2 12 2ZM4 20C4 19.4477 4.44772 19 5 19H19C19.5523 19 20 19.4477 20 20C20 20.5523 19.5523 21 19 21H5C4.44772 21 4 20.5523 4 20Z" />
        </svg>
      );
    case "drop_arrow_down":
      return (
        <svg width={200} height={200} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <g id="SVGRepo_bgCarrier" strokeWidth="0"></g>
          <g id="SVGRepo_tracerCarrier" strokeLinecap="round" strokeLinejoin="round"></g>
          <g id="SVGRepo_iconCarrier">
            {" "}
            <path
              fillRule="evenodd"
              clipRule="evenodd"
              d="M12.7071 14.7071C12.3166 15.0976 11.6834 15.0976 11.2929 14.7071L6.29289 9.70711C5.90237 9.31658 5.90237 8.68342 6.29289 8.29289C6.68342 7.90237 7.31658 7.90237 7.70711 8.29289L12 12.5858L16.2929 8.29289C16.6834 7.90237 17.3166 7.90237 17.7071 8.29289C18.0976 8.68342 18.0976 9.31658 17.7071 9.70711L12.7071 14.7071Z"
              fill="#ffffff"></path>{" "}
          </g>
        </svg>
      );
    case "drop_arrow_up":
      return (
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" transform="rotate(180)" width={200} height={200}>
          <g id="SVGRepo_bgCarrier" strokeWidth="0"></g>
          <g id="SVGRepo_tracerCarrier" strokeLinecap="round" strokeLinejoin="round"></g>
          <g id="SVGRepo_iconCarrier">
            {" "}
            <path
              fillRule="evenodd"
              clipRule="evenodd"
              d="M12.7071 14.7071C12.3166 15.0976 11.6834 15.0976 11.2929 14.7071L6.29289 9.70711C5.90237 9.31658 5.90237 8.68342 6.29289 8.29289C6.68342 7.90237 7.31658 7.90237 7.70711 8.29289L12 12.5858L16.2929 8.29289C16.6834 7.90237 17.3166 7.90237 17.7071 8.29289C18.0976 8.68342 18.0976 9.31658 17.7071 9.70711L12.7071 14.7071Z"
              fill="#ffffff"></path>{" "}
          </g>
        </svg>
      );
    case "file":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <path
            d="M4.00016 9.33334L5.00016 7.4C5.10888 7.1841 5.27424 7.00181 5.47857 6.87264C5.6829 6.74346 5.9185 6.67227 6.16016 6.66667H13.3335M13.3335 6.66667C13.5372 6.66631 13.7382 6.71263 13.9213 6.80206C14.1043 6.89149 14.2643 7.02166 14.3892 7.18258C14.5141 7.3435 14.6004 7.53089 14.6416 7.73037C14.6828 7.92985 14.6778 8.13612 14.6268 8.33334L13.6002 12.3333C13.5259 12.621 13.3576 12.8757 13.1221 13.0569C12.8866 13.238 12.5973 13.3353 12.3002 13.3333H2.66683C2.31321 13.3333 1.97407 13.1929 1.72402 12.9428C1.47397 12.6928 1.3335 12.3536 1.3335 12V3.33334C1.3335 2.97971 1.47397 2.64058 1.72402 2.39053C1.97407 2.14048 2.31321 2 2.66683 2H5.26683C5.48982 1.99782 5.7098 2.0516 5.90663 2.15642C6.10346 2.26124 6.27086 2.41375 6.3935 2.6L6.9335 3.4C7.0549 3.58436 7.22018 3.73568 7.4145 3.84041C7.60881 3.94513 7.82609 3.99997 8.04683 4H12.0002C12.3538 4 12.6929 4.14048 12.943 4.39053C13.193 4.64058 13.3335 4.97971 13.3335 5.33334V6.66667Z"
            stroke="currentColor"
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "detail":
      return (
        <svg style={svgStyle} viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
          <g id="SVGRepo_bgCarrier" strokeWidth="0" />

          <g id="SVGRepo_tracerCarrier" strokeLinecap="round" strokeLinejoin="round" />

          <g id="SVGRepo_iconCarrier">
            {" "}
            <path d="M15 1H1V3H15V1Z" fill="#ffffff" /> <path d="M11 5H1V7H6.52779C7.62643 5.7725 9.223 5 11 5Z" fill="#ffffff" />{" "}
            <path d="M5.34141 13C5.60482 13.7452 6.01127 14.4229 6.52779 15H1V13H5.34141Z" fill="#ffffff" />{" "}
            <path d="M5.34141 9C5.12031 9.62556 5 10.2987 5 11H1V9H5.34141Z" fill="#ffffff" />{" "}
            <path
              d="M15 11C15 11.7418 14.7981 12.4365 14.4462 13.032L15.9571 14.5429L14.5429 15.9571L13.032 14.4462C12.4365 14.7981 11.7418 15 11 15C8.79086 15 7 13.2091 7 11C7 8.79086 8.79086 7 11 7C13.2091 7 15 8.79086 15 11Z"
              fill="#ffffff"
            />{" "}
          </g>
        </svg>
      );
    case "fa-regular fa-copy":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke={color || fill}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true">
          <rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect>
          <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path>
        </svg>
      );
    case "eyeIcon":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <g id="SVGRepo_bgCarrier" strokeWidth="0" />

          <g id="SVGRepo_tracerCarrier" strokeLinecap="round" strokeLinejoin="round" />

          <g id="SVGRepo_iconCarrier">
            {" "}
            <path
              d="M15.0007 12C15.0007 13.6569 13.6576 15 12.0007 15C10.3439 15 9.00073 13.6569 9.00073 12C9.00073 10.3431 10.3439 9 12.0007 9C13.6576 9 15.0007 10.3431 15.0007 12Z"
              stroke={svgStyle.fill}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />{" "}
            <path
              d="M12.0012 5C7.52354 5 3.73326 7.94288 2.45898 12C3.73324 16.0571 7.52354 19 12.0012 19C16.4788 19 20.2691 16.0571 21.5434 12C20.2691 7.94291 16.4788 5 12.0012 5Z"
              stroke={svgStyle.fill}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />{" "}
          </g>
        </svg>
      );
    case "eye":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke={color || fill}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height }}>
          <path d="M12 5C7.455 5 3.734 7.943 2.46 12C3.734 16.057 7.455 19 12 19C16.545 19 20.266 16.057 21.54 12C20.266 7.943 16.545 5 12 5Z" />
          <circle cx="12" cy="12" r="3" />
        </svg>
      );
    case "eye-slash":
      return (
        <svg {...svgStyle} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
          <path d="M3 3L21 21" stroke={svgStyle.fill} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path
            d="M10.58 10.58C10.21 10.95 10 11.45 10 12C10 13.1 10.9 14 12 14C12.55 14 13.05 13.79 13.42 13.42"
            stroke={svgStyle.fill}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M9.88 4.12C10.57 4.04 11.28 4 12 4C16.545 4 20.266 6.943 21.54 11C21.1 12.42 20.34 13.68 19.37 14.68M6.34 6.34C4.66 7.5 3.4 9.57 2.46 12C3.734 16.057 7.455 19 12 19C13.5 19 14.91 18.68 16.18 18.11"
            stroke={svgStyle.fill}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "metrics":
      return (
        <svg {...svgStyle} xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
          <rect x="3" y="13" width="4" height="8" rx="1" fill={svgStyle.fill} />
          <rect x="9" y="9" width="4" height="12" rx="1" fill={svgStyle.fill} />
          <rect x="15" y="5" width="4" height="16" rx="1" fill={svgStyle.fill} />
        </svg>
      );
    case "warnings":
      return (
        <svg {...svgStyle} xmlns="http://www.w3.org/2000/svg" viewBox="-4 -2 32 32" fill="none">
          <polygon points="12,3 2,21 22,21" fill="#FFD600" stroke="#B8860B" strokeWidth="1.5" />
          <rect x="11" y="9" width="2" height="6" rx="1" fill="#B8860B" />
          <circle cx="12" cy="18" r="1.2" fill="#B8860B" />
        </svg>
      );
    case "tableIcon":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2"></rect>
          <path d="M3 9h18"></path>
          <path d="M3 15h18"></path>
          <path d="M9 3v18"></path>
          <path d="M15 3v18"></path>
        </svg>
      );
    case "accordionIcon":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M3 5h.01"></path>
          <path d="M3 12h.01"></path>
          <path d="M3 19h.01"></path>
          <path d="M8 5h13"></path>
          <path d="M8 12h13"></path>
          <path d="M8 19h13"></path>
        </svg>
      );
    case "fa-solid fa-up-right-and-down-left-from-center":
      // FontAwesome expand icon (up-right-and-down-left-from-center)
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" {...svgStyle}>
          <path d="M320 32c0-17.7 14.3-32 32-32h128c17.7 0 32 14.3 32 32v128c0 17.7-14.3 32-32 32s-32-14.3-32-32V83.3L329 234.3c-12.5 12.5-32.8 12.5-45.3 0s-12.5-32.8 0-45.3L434.7 64H352c-17.7 0-32-14.3-32-32zM192 480c0 17.7-14.3 32-32 32H32c-17.7 0-32-14.3-32-32V352c0-17.7 14.3-32 32-32s32 14.3 32 32v44.7L183 277.7c12.5-12.5 32.8-12.5 45.3 0s12.5 32.8 0 45.3L77.3 448H160c17.7 0 32 14.3 32 32z" />
        </svg>
      );
    case "ground-truth":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <path
            d="M2 2V12.6667C2 13.0203 2.14048 13.3594 2.39052 13.6095C2.64057 13.8595 2.97971 14 3.33333 14H14"
            stroke="currentColor"
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M12 11.3333V6" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M8.6665 11.3333V3.33334" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M5.3335 11.3333V9.33334" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "data-connectors":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={stroke || color || "currentColor"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width, height, color }}>
          <path d="m19 5 3-3" />
          <path d="m2 22 3-3" />
          <path d="M6.3 20.3a2.4 2.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4Z" />
          <path d="M7.5 13.5 10 11" />
          <path d="M10.5 16.5 13 14" />
          <path d="m12 6 6 6 2.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0Z" />
        </svg>
      );
    case "server":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" style={{ width, height, color }}>
          <rect width="20" height="8" x="2" y="2" rx="2" ry="2" stroke={stroke || color || "currentColor"} strokeWidth="1.5" />
          <rect width="20" height="8" x="2" y="14" rx="2" ry="2" stroke={stroke || color || "currentColor"} strokeWidth="1.5" />
          <circle cx="6" cy="6" r="1" fill={stroke || color || "currentColor"} />
          <circle cx="6" cy="18" r="1" fill={stroke || color || "currentColor"} />
        </svg>
      );
    case "database":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512" {...svgStyle}>
          <path d="M448 80v48c0 44.2-100.3 80-224 80S0 172.2 0 128V80C0 35.8 100.3 0 224 0S448 35.8 448 80zM393.2 214.7c20.8-7.4 39.9-16.9 54.8-28.6V288c0 44.2-100.3 80-224 80S0 332.2 0 288V186.1c14.9 11.8 34 21.2 54.8 28.6C99.7 230.7 159.5 240 224 240s124.3-9.3 169.2-25.3zM0 346.1c14.9 11.8 34 21.2 54.8 28.6C99.7 390.7 159.5 400 224 400s124.3-9.3 169.2-25.3c20.8-7.4 39.9-16.9 54.8-28.6V432c0 44.2-100.3 80-224 80S0 476.2 0 432V346.1z" />
        </svg>
      );
      
    case "postgresql":
      return (
        <img
          src={postgresqlIcon}
          alt="PostgreSQL"
          style={{
            width: width,
            height: height,
            objectFit: "contain",
          }}
        />
      );
    case "mysql":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 -20 73 73" style={{ width, height }}>
          <path d="m21.72 24.79c-1.143 6.217-2.65 10.74-4.521 13.55-1.458 2.172-3.055 3.258-4.794 3.258-0.4636 0-1.035-0.14-1.714-0.4182v-1.499c0.3314 0.04865 0.7203 0.07461 1.167 0.07461 0.8113 0 1.465-0.2248 1.963-0.6735 0.5957-0.5468 0.8938-1.161 0.8938-1.842 0-0.4652-0.2325-1.42-0.6955-2.864l-3.08-9.589h2.757l2.21 7.172c0.4966 1.628 0.7037 2.765 0.6208 3.413 1.209-3.238 2.054-6.766 2.534-10.58h2.658m-12.17 12.4h-2.806c-0.09869-4.749-0.3723-9.215-0.8194-13.4h-0.02472l-4.273 13.4h-2.137l-4.247-13.4h-0.02502c-0.3151 4.018-0.5134 8.483-0.596 13.4h-2.559c0.1653-5.978 0.5792-11.58 1.241-16.81h3.478l4.049 12.35h0.02484l4.074-12.35h3.328c0.7287 6.126 1.159 11.73 1.291 16.81" fill={fill || "#00758f"}/>
          <path d="m59.08 37.19h-7.973v-16.81h2.683v14.74h5.29v2.068m-20.05-3.363c-0.6791-1.096-1.019-2.854-1.019-5.279 0-4.233 1.284-6.351 3.85-6.351 1.342 0 2.327 0.5066 2.956 1.519 0.6783 1.096 1.018 2.84 1.018 5.231 0 4.267-1.284 6.402-3.85 6.402-1.341 0-2.327-0.506-2.955-1.52m9.985 3.768-3.082-1.524c0.2744-0.2256 0.535-0.4691 0.7709-0.7509 1.309-1.542 1.963-3.825 1.963-6.848 0-5.562-2.178-8.344-6.533-8.344-2.136 0-3.801 0.7053-4.993 2.118-1.309 1.544-1.963 3.819-1.963 6.824 0 2.955 0.5792 5.123 1.738 6.5 1.056 1.245 2.653 1.868 4.792 1.868 0.7977 0 1.53-0.09848 2.195-0.2955l4.013 2.342 1.094-1.89m-15-5.065c0 1.426-0.5224 2.596-1.564 3.512-1.042 0.9118-2.443 1.369-4.196 1.369-1.64 0-3.229-0.5261-4.769-1.57l0.7203-1.444c1.325 0.6641 2.524 0.9957 3.6 0.9957 1.01 0 1.8-0.2253 2.372-0.6705 0.5705-0.4484 0.9124-1.074 0.9124-1.867 0-0.9982-0.6943-1.851-1.968-2.567-1.176-0.6471-3.526-1.998-3.526-1.998-1.273-0.9314-1.912-1.931-1.912-3.577 0-1.362 0.4761-2.463 1.427-3.3 0.9531-0.8392 2.183-1.259 3.689-1.259 1.557 0 2.972 0.4165 4.247 1.247l-0.6475 1.443c-1.091-0.4637-2.166-0.6964-3.227-0.6964-0.8605 0-1.524 0.2072-1.986 0.6239-0.4649 0.4131-0.7523 0.9448-0.7523 1.593 0 0.9956 0.7094 1.859 2.019 2.589 1.191 0.6474 3.599 2.025 3.599 2.025 1.31 0.9297 1.963 1.921 1.963 3.554" fill={fill || "#f29111"}/>
          <path d="m60.99 37.19h0.4445v-1.71h0.5818v-0.3494h-1.631v0.3494h0.6043zm3.383 0h0.419v-2.06h-0.6302l-0.5129 1.404-0.5584-1.404h-0.6073v2.06h0.3965v-1.568h0.02253l0.5848 1.568h0.3021l0.5839-1.568v1.568" fill={fill || "#f29111"}/>
          <path d="m36.78-7.929c-0.7089-0.01057-1.327 0.2572-1.646 1.042-0.5471 1.321 0.8104 2.62 1.277 3.291 0.3441 0.4666 0.7901 0.9956 1.032 1.523 0.142 0.3455 0.183 0.7118 0.3254 1.077 0.3238 0.8936 0.627 1.889 1.053 2.723 0.2221 0.4266 0.4649 0.8738 0.7485 1.258 0.1636 0.2248 0.4462 0.325 0.5073 0.6917-0.2827 0.4058-0.3048 1.015-0.4666 1.524-0.7289 2.295-0.4459 5.139 0.5878 6.825 0.3233 0.5077 1.094 1.625 2.128 1.198 0.9116-0.365 0.7089-1.523 0.9721-2.538 0.06059-0.2455 0.02007-0.4065 0.1413-0.5688v0.04099c0.2835 0.5679 0.568 1.115 0.8312 1.686 0.6289 0.9943 1.722 2.03 2.634 2.72 0.4848 0.367 0.8702 0.9957 1.478 1.22v-0.06149h-0.0399c-0.1221-0.1823-0.304-0.264-0.4663-0.4055-0.3645-0.3659-0.7685-0.8131-1.053-1.219-0.8505-1.137-1.601-2.397-2.268-3.697-0.3251-0.6312-0.6082-1.321-0.8718-1.95-0.1212-0.2426-0.1213-0.6093-0.3243-0.7309-0.3047 0.4464-0.7492 0.8327-0.9717 1.379-0.3852 0.8745-0.4255 1.951-0.5684 3.068-0.08051 0.02122-0.03983 1.88e-4-0.08052 0.04062-0.6475-0.1624-0.8704-0.8327-1.114-1.4-0.6077-1.444-0.7099-3.76-0.1823-5.425 0.1411-0.4258 0.7507-1.766 0.5065-2.173-0.1225-0.3876-0.5274-0.609-0.7499-0.915-0.2627-0.3858-0.5478-0.8725-0.7283-1.3-0.4865-1.137-0.731-2.397-1.256-3.534-0.2433-0.529-0.6698-1.077-1.013-1.564-0.3857-0.5486-0.8105-0.9344-1.115-1.584-0.1004-0.2239-0.2423-0.59-0.08089-0.833 0.03982-0.1628 0.1221-0.2238 0.2844-0.2646 0.2619-0.2235 1.012 0.06031 1.275 0.1823 0.7501 0.3038 1.378 0.5895 2.005 1.015 0.2839 0.2035 0.5879 0.5897 0.952 0.6921h0.4264c0.648 0.1411 1.378 0.03931 1.986 0.2229 1.073 0.345 2.045 0.8528 2.917 1.401 2.653 1.686 4.841 4.084 6.319 6.947 0.2437 0.4666 0.3459 0.8933 0.5684 1.38 0.4255 0.9973 0.953 2.013 1.378 2.987 0.4251 0.9548 0.8309 1.929 1.439 2.722 0.303 0.4258 1.519 0.6493 2.066 0.8729 0.4043 0.1822 1.033 0.3449 1.398 0.568 0.6887 0.4258 1.376 0.9141 2.025 1.382 0.3233 0.2438 1.336 0.7511 1.397 1.158l3.72e-4 3.75e-4c-1.621-0.04066-2.877 0.1215-3.93 0.5688-0.3039 0.1217-0.7896 0.1216-0.8312 0.5076 0.1632 0.1622 0.1829 0.4263 0.3257 0.6507 0.2424 0.4062 0.6669 0.9538 1.053 1.239 0.4255 0.3252 0.8508 0.649 1.297 0.9333 0.7895 0.4896 1.681 0.7728 2.45 1.26 0.4471 0.284 0.8913 0.6494 1.338 0.9549 0.2221 0.1624 0.3626 0.4269 0.6474 0.5274v-0.06185c-0.1428-0.1823-0.1824-0.4461-0.3235-0.6504-0.2021-0.2016-0.4053-0.3855-0.6083-0.5878-0.5878-0.7921-1.318-1.482-2.106-2.051-0.6488-0.4481-2.068-1.058-2.33-1.807 0 0-0.02144-0.02135-0.04135-0.04135 0.4458-0.04123 0.9738-0.204 1.399-0.3272 0.6878-0.1823 1.316-0.1413 2.025-0.3235 0.3246-0.08185 0.6488-0.1838 0.9743-0.2836v-0.1841c-0.3666-0.3648-0.6286-0.8533-1.013-1.198-1.032-0.8934-2.168-1.766-3.343-2.499-0.6289-0.4064-1.439-0.6691-2.108-1.015-0.242-0.1221-0.6467-0.1822-0.7891-0.3865-0.3649-0.4467-0.5684-1.035-0.8312-1.564-0.5869-1.116-1.155-2.355-1.661-3.535-0.3645-0.7916-0.5874-1.583-1.033-2.315-2.088-3.454-4.356-5.545-7.84-7.597-0.7497-0.4271-1.641-0.6095-2.592-0.833-0.5073-0.02127-1.013-0.06092-1.52-0.08088-0.3246-0.1428-0.6495-0.5292-0.9326-0.7119-0.722-0.4568-2.156-1.247-3.337-1.265zm4.998 5.021c-0.3437 0-0.5862 0.04178-0.8308 0.1021v0.04063h0.03953c0.1636 0.3242 0.4477 0.5495 0.6485 0.8334 0.1632 0.3251 0.3051 0.6488 0.467 0.9743 0.0199-0.01996 0.03917-0.04099 0.03917-0.04099 0.2857-0.2022 0.4275-0.527 0.4275-1.015-0.1225-0.1432-0.1416-0.2843-0.2438-0.4271-0.1212-0.2027-0.3848-0.3043-0.5472-0.467z" fill={fill || "#00758f"}/>
        </svg>
      );
    case "mongodb":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" style={{ width, height }}>
          <path fill={fill || "#47A248"} d="M17.193 9.555c-1.264-5.58-4.252-7.414-4.573-8.115-.28-.394-.53-.954-.735-1.44-.036.495-.055.685-.523 1.184-.723.566-4.438 3.682-4.74 10.02-.282 5.912 4.27 9.435 4.888 9.884l.07.05A73.49 73.49 0 0 1 11.91 24h.481c.114-1.032.284-2.056.51-3.07.417-.296.604-.463.85-.693a11.342 11.342 0 0 0 3.639-8.464c.01-.814-.103-1.662-.197-2.218zm-5.336 8.195s0-8.291.275-8.29c.213 0 .49 10.695.49 10.695-.381-.045-.765-1.76-.765-2.405z" />
        </svg>
      );
    case "sqlite":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 18}
          height={height || 18}
          viewBox="0 0 24 24"
          fill="none"
          stroke={fill || color || "#003B57"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="17 8 12 3 7 8"></polyline>
          <line x1="12" x2="12" y1="3" y2="15"></line>
        </svg>
      );
    case "close":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" {...svgStyle}>
          <path d="M376.6 84.5c11.3-13.6 9.5-33.8-4.1-45.1s-33.8-9.5-45.1 4.1L192 206 56.6 43.5C45.3 29.9 25.1 28.1 11.5 39.4S-3.9 70.9 7.4 84.5L150.3 256 7.4 427.5c-11.3 13.6-9.5 33.8 4.1 45.1s33.8 9.5 45.1-4.1L192 306 327.4 468.5c11.3 13.6 31.5 15.4 45.1 4.1s15.4-31.5 4.1-45.1L233.7 256 376.6 84.5z" />
        </svg>
      );
    case "plug":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" {...svgStyle}>
          <path d="M96 0C78.3 0 64 14.3 64 32v96h64V32c0-17.7-14.3-32-32-32zM288 0c-17.7 0-32 14.3-32 32v96h64V32c0-17.7-14.3-32-32-32zM32 160c-17.7 0-32 14.3-32 32s14.3 32 32 32v32c0 77.4 55 142 128 156.8V480c0 17.7 14.3 32 32 32s32-14.3 32-32V412.8C297 398 352 333.4 352 256V224c17.7 0 32-14.3 32-32s-14.3-32-32-32H32z" />
        </svg>
      );
    case "play":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512" {...svgStyle}>
          <path d="M73 39c-14.8-9.1-33.4-9.4-48.5-.9S0 62.6 0 80L0 432c0 17.4 9.4 33.4 24.5 41.9s33.7 8.1 48.5-.9L361 297c14.3-8.7 23-24.2 23-41s-8.7-32.2-23-41L73 39z" />
        </svg>
      );
    case "settings":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <path
            d="M8 10C9.10457 10 10 9.10457 10 8C10 6.89543 9.10457 6 8 6C6.89543 6 6 6.89543 6 8C6 9.10457 6.89543 10 8 10Z"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M12.9333 10C12.8445 10.2024 12.818 10.4261 12.8573 10.6432C12.8965 10.8603 12.9997 11.0609 13.1533 11.22L13.1933 11.26C13.3174 11.3839 13.4158 11.5312 13.4829 11.6934C13.55 11.8556 13.5844 12.0296 13.5844 12.2053C13.5844 12.381 13.55 12.555 13.4829 12.7172C13.4158 12.8794 13.3174 13.0267 13.1933 13.1507C13.0694 13.2748 12.9221 13.3731 12.7599 13.4402C12.5977 13.5073 12.4237 13.5417 12.248 13.5417C12.0723 13.5417 11.8983 13.5073 11.7361 13.4402C11.5739 13.3731 11.4266 13.2748 11.3027 13.1507L11.2627 13.1107C11.1035 12.957 10.9029 12.8539 10.6858 12.8146C10.4687 12.7754 10.2451 12.8019 10.0427 12.8907C9.84435 12.9752 9.67398 13.1157 9.55299 13.2945C9.43201 13.4734 9.36565 13.6831 9.36267 13.898V14C9.36267 14.3536 9.22219 14.6928 8.97214 14.9428C8.7221 15.1929 8.38296 15.3333 8.02933 15.3333C7.67571 15.3333 7.33657 15.1929 7.08652 14.9428C6.83648 14.6928 6.696 14.3536 6.696 14V13.9447C6.68874 13.7236 6.61456 13.5099 6.48325 13.3306C6.35194 13.1512 6.16956 13.0145 5.96 12.938C5.75759 12.8492 5.53399 12.8227 5.31686 12.8619C5.09974 12.9012 4.89917 13.0043 4.74 13.158L4.7 13.198C4.57607 13.3221 4.42879 13.4205 4.26658 13.4876C4.10437 13.5547 3.93037 13.5891 3.75467 13.5891C3.57897 13.5891 3.40497 13.5547 3.24276 13.4876C3.08054 13.4205 2.93327 13.3221 2.80933 13.198C2.6853 13.0741 2.58693 12.9268 2.51982 12.7646C2.45271 12.6024 2.41832 12.4284 2.41832 12.2527C2.41832 12.077 2.45271 11.903 2.51982 11.7408C2.58693 11.5785 2.6853 11.4313 2.80933 11.3073L2.84933 11.2673C3.00303 11.1082 3.10612 10.9076 3.14538 10.6905C3.18464 10.4734 3.15814 10.2497 3.06933 10.0473C2.98483 9.84902 2.84434 9.67865 2.66551 9.55767C2.48668 9.43668 2.27698 9.37032 2.062 9.36733H2C1.64638 9.36733 1.30724 9.22686 1.05719 8.97681C0.807142 8.72676 0.666668 8.38762 0.666668 8.034C0.666668 7.68038 0.807142 7.34124 1.05719 7.09119C1.30724 6.84114 1.64638 6.70067 2 6.70067H2.05533C2.27645 6.69341 2.49014 6.61922 2.66951 6.48791C2.84888 6.35661 2.98559 6.17422 3.062 5.96467C3.15081 5.76225 3.17731 5.53866 3.13805 5.32153C3.09879 5.10441 2.99571 4.90383 2.842 4.74467L2.802 4.70467C2.67797 4.58073 2.5796 4.43346 2.51249 4.27124C2.44538 4.10903 2.41099 3.93503 2.41099 3.75933C2.41099 3.58363 2.44538 3.40963 2.51249 3.24742C2.5796 3.08521 2.67797 2.93793 2.802 2.814C2.92593 2.68997 3.07321 2.5916 3.23542 2.52449C3.39763 2.45738 3.57163 2.42299 3.74733 2.42299C3.92303 2.42299 4.09703 2.45738 4.25924 2.52449C4.42146 2.5916 4.56873 2.68997 4.69267 2.814L4.73267 2.854C4.89183 3.00771 5.09241 3.11079 5.30953 3.15005C5.52666 3.18931 5.75025 3.16281 5.95267 3.074H6C6.19835 2.9895 6.36872 2.84902 6.48971 2.67018C6.61069 2.49135 6.67705 2.28165 6.68 2.06667V2C6.68 1.64638 6.82048 1.30724 7.07052 1.05719C7.32057 0.807142 7.65971 0.666668 8.01333 0.666668C8.36696 0.666668 8.70609 0.807142 8.95614 1.05719C9.20619 1.30724 9.34667 1.64638 9.34667 2V2.05533C9.34961 2.27032 9.41597 2.48001 9.53696 2.65885C9.65794 2.83768 9.82831 2.97817 10.0267 3.06267C10.2291 3.15148 10.4527 3.17798 10.6698 3.13872C10.887 3.09946 11.0875 2.99637 11.2467 2.84267L11.2867 2.80267C11.4106 2.67864 11.5579 2.58027 11.7201 2.51316C11.8823 2.44605 12.0563 2.41166 12.232 2.41166C12.4077 2.41166 12.5817 2.44605 12.7439 2.51316C12.9061 2.58027 13.0534 2.67864 13.1773 2.80267C13.3014 2.9266 13.3997 3.07388 13.4668 3.23609C13.534 3.3983 13.5683 3.5723 13.5683 3.748C13.5683 3.9237 13.534 4.0977 13.4668 4.25991C13.3997 4.42212 13.3014 4.5694 13.1773 4.69333L13.1373 4.73333C12.9836 4.8925 12.8806 5.09307 12.8413 5.3102C12.802 5.52732 12.8285 5.75091 12.9173 5.95333V6C13.0018 6.19835 13.1423 6.36872 13.3212 6.48971C13.5 6.61069 13.7097 6.67705 13.9247 6.68H14C14.3536 6.68 14.6928 6.82048 14.9428 7.07052C15.1929 7.32057 15.3333 7.65971 15.3333 8.01333C15.3333 8.36696 15.1929 8.70609 14.9428 8.95614C14.6928 9.20619 14.3536 9.34667 14 9.34667H13.9447C13.7297 9.34961 13.52 9.41597 13.3412 9.53696C13.1623 9.65794 13.0218 9.82831 12.9373 10.0267L12.9333 10Z"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "clipboard-check":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color }}>
          <path
            d="M10.6667 2.66667H12C12.3536 2.66667 12.6928 2.80714 12.9428 3.05719C13.1929 3.30724 13.3333 3.64638 13.3333 4V13.3333C13.3333 13.687 13.1929 14.0261 12.9428 14.2761C12.6928 14.5262 12.3536 14.6667 12 14.6667H4C3.64638 14.6667 3.30724 14.5262 3.05719 14.2761C2.80714 14.0261 2.66667 13.687 2.66667 13.3333V4C2.66667 3.64638 2.80714 3.30724 3.05719 3.05719C3.30724 2.80714 3.64638 2.66667 4 2.66667H5.33333"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M9.33333 1.33334H6.66667C6.29848 1.33334 6 1.63181 6 2V3.33334C6 3.70153 6.29848 4 6.66667 4H9.33333C9.70152 4 10 3.70153 10 3.33334V2C10 1.63181 9.70152 1.33334 9.33333 1.33334Z"
            stroke={stroke || color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M6 8L7.33333 9.33333L10.6667 6" stroke={stroke || color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "fa-chart-bar":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
          <rect x="3" y="13" width="4" height="8" fill="currentColor" rx="1" />
          <rect x="10" y="9" width="4" height="12" fill="currentColor" rx="1" />
          <rect x="17" y="5" width="4" height="16" fill="currentColor" rx="1" />
        </svg>
      );
    case "fa-chart-line":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
          <polyline points="3,17 6,11 12,13 18,7" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="3" cy="17" r="2" fill="currentColor" />
          <circle cx="6" cy="11" r="2" fill="currentColor" />
          <circle cx="12" cy="13" r="2" fill="currentColor" />
          <circle cx="18" cy="7" r="2" fill="currentColor" />
        </svg>
      );
    case "fa-chart-area":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
          <path d="M3 17L6 11L12 13L18 7V20H3V17Z" fill="currentColor" fillOpacity="0.3" />
          <polyline points="3,17 6,11 12,13 18,7" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "fa-chart-pie":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
          <path d="M12 2V12L20.5 6.5C19.1 4.4 15.8 2 12 2Z" fill="currentColor" />
          <path d="M12 2C6.5 2 2 6.5 2 12C2 17.5 6.5 22 12 22C17.5 22 22 17.5 22 12L12 12V2Z" stroke="currentColor" strokeWidth="2" fill="none" />
        </svg>
      );
    case "fa-chart-column":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
          <rect x="3" y="13" width="4" height="8" fill="currentColor" rx="1" />
          <rect x="10" y="9" width="4" height="12" fill="currentColor" rx="1" />
          <rect x="17" y="5" width="4" height="16" fill="currentColor" rx="1" />
        </svg>
      );
    case "fa-braille":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
          <circle cx="6" cy="6" r="2" fill="currentColor" />
          <circle cx="18" cy="6" r="2" fill="currentColor" />
          <circle cx="6" cy="12" r="2" fill="currentColor" />
          <circle cx="18" cy="12" r="2" fill="currentColor" />
          <circle cx="6" cy="18" r="2" fill="currentColor" />
          <circle cx="18" cy="18" r="2" fill="currentColor" />
        </svg>
      );
    case "fa-magic":
      return (
        <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
          <path
            d="M3 3L21 21M9 9L15 15M12 2L13 7L18 6L13 11L12 16L11 11L6 12L11 7L12 2Z"
            stroke="currentColor"
            strokeWidth="2"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "fa-image":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" {...svgStyle}>
          <path d="M0 96C0 60.7 28.7 32 64 32H448c35.3 0 64 28.7 64 64V416c0 35.3-28.7 64-64 64H64c-35.3 0-64-28.7-64-64V96zM323.8 202.5c-4.5-6.6-11.9-10.5-19.8-10.5s-15.4 3.9-19.8 10.5l-87 127.6L170.7 297c-4.6-5.7-11.5-9-18.7-9s-14.2 3.3-18.7 9l-64 80c-5.8 7.2-6.9 17.1-2.9 25.4s12.4 13.6 21.6 13.6h96 32 208c8.9 0 17.1-4.9 21.2-12.8s3.6-17.4-1.4-24.7l-120-176zM112 192a48 48 0 1 0 0-96 48 48 0 1 0 0 96z" />
        </svg>
      );
    case "fa-exclamation-triangle":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" {...svgStyle}>
          <path d="M506.3 417l-213.3-364c-16.33-28-57.54-28-73.98 0l-213.2 364C-10.59 444.9 9.849 480 42.74 480h426.6C502.1 480 522.6 445 506.3 417zM232 168c0-13.25 10.75-24 24-24S280 154.8 280 168v128c0 13.25-10.75 24-23.1 24S232 309.3 232 296V168zM256 416c-17.36 0-31.44-14.08-31.44-31.44c0-17.36 14.07-31.44 31.44-31.44s31.44 14.08 31.44 31.44C287.4 401.9 273.4 416 256 416z" />
        </svg>
      );
    case "thermometerIcon":
      return (
        <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" color="none" {...svgStyle}>
          <rect x="28" y="10" width="8" height="32" rx="4" stroke={fill} strokeWidth="3" fill="none" />
          <circle cx="32" cy="50" r="10" stroke={fill} strokeWidth="3" fill="none" />
          <circle cx="32" cy="50" r="6" fill={fill} />
          <line x1="44" y1="18" x2="54" y2="18" stroke={fill} strokeWidth="3" strokeLinecap="round" />
          <line x1="44" y1="26" x2="54" y2="26" stroke={fill} strokeWidth="3" strokeLinecap="round" />
          <line x1="44" y1="34" x2="54" y2="34" stroke={fill} strokeWidth="3" strokeLinecap="round" />
          <line x1="44" y1="42" x2="54" y2="42" stroke={fill} strokeWidth="3" strokeLinecap="round" />
        </svg>
      );
    case "save":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" {...svgStyle}>
          <rect x="3" y="3" width="18" height="18" rx="2" stroke="currentColor" strokeWidth="2" fill="none" />
          <rect x="7" y="3" width="10" height="6" fill="currentColor" fillOpacity="0.3" />
          <rect x="7" y="3" width="10" height="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
          <rect x="6" y="13" width="12" height="8" rx="1" fill="currentColor" fillOpacity="0.2" />
          <rect x="9" y="16" width="6" height="2" rx="0.5" fill="currentColor" />
        </svg>
      );
    case "update":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {...svgStyle}>
          {/* Circular arc */}
          <path d="M12 4a8 8 0 1 1-7.5 5.3" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
          {/* Bold, sharp triangle arrowhead */}
          <path d="M1.5 7 L7.5 5 L8 11.5 Z" fill="currentColor" />
        </svg>
      );
    case "grafana":
      return (
        <img
          src={grafanaIcon}
          alt="Grafana"
          style={{
            width: width,
            height: height,
            objectFit: "contain",
          }}
        />
      );
    case "upload-old":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          {...svgStyle}>
          <path d="M12 3v12" />
          <path d="m17 8-5-5-5 5" />
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
        </svg>
      );
    case "upload-new":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" {...svgStyle}>
          <path d="M12 3v12M7 8l5-5 5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "layout-grid":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color }}>
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
        </svg>
      );
    case "list":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color }}>
          <path d="M3 5h.01" />
          <path d="M3 12h.01" />
          <path d="M3 19h.01" />
          <path d="M8 5h13" />
          <path d="M8 12h13" />
          <path d="M8 19h13" />
        </svg>
      );
    case "refresh":
      return (
        <svg
          style={svgStyle}
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true">
          <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path>
          <path d="M21 3v5h-5"></path>
          <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path>
          <path d="M8 16H3v5"></path>
        </svg>
      );

    case "refresh-new":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width={width || 16} height={height || 16} viewBox="0 0 16 16" fill="none">
          <path
            d="M2 8C2 6.4087 2.63214 4.88258 3.75736 3.75736C4.88258 2.63214 6.4087 2 8 2C9.67737 2.00631 11.2874 2.66082 12.4933 3.82667L14 5.33333"
            stroke={color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M13.9998 2V5.33333H10.6665" stroke={color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path
            d="M14 8C14 9.5913 13.3679 11.1174 12.2426 12.2426C11.1174 13.3679 9.5913 14 8 14C6.32263 13.9937 4.71265 13.3392 3.50667 12.1733L2 10.6667"
            stroke={color || "currentColor"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M5.33333 10.6667H2V14" stroke={color || "currentColor"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );

    case "info-modern":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" {...svgStyle} viewBox="0 0 14 14" fill="none">
          <g clipPath="url(#clip0_169_11433)">
            <path
              d="M7.00033 12.8333C10.222 12.8333 12.8337 10.2217 12.8337 6.99999C12.8337 3.77833 10.222 1.16666 7.00033 1.16666C3.77866 1.16666 1.16699 3.77833 1.16699 6.99999C1.16699 10.2217 3.77866 12.8333 7.00033 12.8333Z"
              stroke="#6b7280"
              strokeWidth="1.16667"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M7 9.33333V7" stroke="#6b7280" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M7 4.66666H7.00583" stroke="#6b7280" strokeWidth="1.16667" strokeLinecap="round" strokeLinejoin="round" />
          </g>
          <defs>
            <clipPath id="clip0_169_11433">
              <rect width="14" height="14" fill="white" />
            </clipPath>
          </defs>
        </svg>
      );
    case "message-square":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          {...svgStyle}
          viewBox="0 0 24 24"
          fill="none"
          stroke={color || fill}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          style={{ width, height, strokeWidth: 2 }}>
          <path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"></path>
        </svg>
      );
    case "plus":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height, color }}>
          <path d="M5 12h14"></path>
          <path d="M12 5v14"></path>
        </svg>
      );
    case "wrench":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height, color }}>
          <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z"></path>
        </svg>
      );
    case "eye2":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height, color }}>
          <path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"></path>
          <circle cx="12" cy="12" r="3"></circle>
        </svg>
      );
    case "chevronRight":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height, color }}>
          <path d="m9 18 6-6-6-6"></path>
        </svg>
      );
    case "fileText":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height }}>
          <path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"></path>
          <path d="M14 2v5a1 1 0 0 0 1 1h5"></path>
          <path d="M10 9H8"></path>
          <path d="M16 13H8"></path>
          <path d="M16 17H8"></path>
        </svg>
      );
    case "folder":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" {...svgStyle}>
          <path d="M64 480H448c35.3 0 64-28.7 64-64V160c0-35.3-28.7-64-64-64H288c-10.1 0-19.6-4.7-25.6-12.8L243.2 57.6C231.1 41.5 212.1 32 192 32H64C28.7 32 0 60.7 0 96V416c0 35.3 28.7 64 64 64z" />
        </svg>
      );
    case "lucide-play":
      // Lucide Play icon from user SVG
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill={fill === "#FFFFFF" ? "none" : fill}
          stroke={stroke || color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          style={{ color: stroke || color, width, height }}>
          <path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"></path>
        </svg>
      );
    case "mic":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
          <line x1="12" x2="12" y1="19" y2="22"></line>
        </svg>
      );
    case "sparkles":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"></path>
          <path d="M20 3v4"></path>
          <path d="M22 5h-4"></path>
          <path d="M4 17v2"></path>
          <path d="M5 18H3"></path>
        </svg>
      );
    case "send":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width={width} height={height} viewBox="0 0 24 24" fill="currentColor">
          <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"></path>
        </svg>
      );
    case "brain":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="#0073cf"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color: "#0073cf" }}>
          <path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z" />
          <path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z" />
          <path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4" />
          <path d="M17.599 6.5a3 3 0 0 0 .399-1.375" />
          <path d="M6.003 5.125A3 3 0 0 0 6.401 6.5" />
          <path d="M3.477 10.896a4 4 0 0 1 .585-.396" />
          <path d="M19.938 10.5a4 4 0 0 1 .585.396" />
          <path d="M6 18a4 4 0 0 1-1.967-.516" />
          <path d="M19.967 17.484A4 4 0 0 1 18 18" />
        </svg>
      );
    case "bolt":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path>
        </svg>
      );
    case "circle-check": {
      const iconColor = color || "#0073cf";

      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="#0073cf"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height, color: iconColor }}>
          <circle cx="12" cy="12" r="10" />
          <path d="m9 12 2 2 4-4" />
        </svg>
      );
    }
    case "circle-x": {
      const iconColor = color || fill || "#dc2626";

      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke={iconColor}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ width, height, color: iconColor }}>
          <circle cx="12" cy="12" r="10" />
          <path d="m15 9-6 6" />
          <path d="m9 9 6 6" />
        </svg>
      );
    }
    case "activity":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"></path>
        </svg>
      );
    case "messages-square":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z"></path>
          <path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1"></path>
        </svg>
      );
    case "thermometer":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z"></path>
        </svg>
      );
    case "sliders-vertical":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <line x1="4" x2="4" y1="21" y2="14"></line>
          <line x1="4" x2="4" y1="10" y2="3"></line>
          <line x1="12" x2="12" y1="21" y2="12"></line>
          <line x1="12" x2="12" y1="8" y2="3"></line>
          <line x1="20" x2="20" y1="21" y2="16"></line>
          <line x1="20" x2="20" y1="12" y2="3"></line>
          <line x1="2" x2="6" y1="14" y2="14"></line>
          <line x1="10" x2="14" y1="8" y2="8"></line>
          <line x1="18" x2="22" y1="16" y2="16"></line>
        </svg>
      );
    case "circle-plus":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <circle cx="12" cy="12" r="10"></circle>
          <path d="M8 12h8"></path>
          <path d="M12 8v8"></path>
        </svg>
      );
    case "trash-2":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M3 6h18"></path>
          <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"></path>
          <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"></path>
          <line x1="10" x2="10" y1="11" y2="17"></line>
          <line x1="14" x2="14" y1="11" y2="17"></line>
        </svg>
      );
    case "thumbs-up":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M7 10v12"></path>
          <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"></path>
        </svg>
      );
    case "thumbs-down":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M17 14V2"></path>
          <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"></path>
        </svg>
      );
    case "rotate-ccw":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
          <path d="M3 3v5h5"></path>
        </svg>
      );
    case "chevron-down":
      return (
        <svg width={width} height={height} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ color }}>
          <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "chevron-left":
      return (
        <svg width={width} height={height} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ color }}>
          <path d="M12 14L8 10L12 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "chevron-right":
      return (
        <svg width={width} height={height} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ color }}>
          <path d="M8 6L12 10L8 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "checkbox-checked":
      return (
        <svg width={width} height={height} viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect width="12" height="12" rx="3" fill={color} />
          <path d="M3 6.5L5.5 9L9 4.5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "close-x":
      return (
        <svg width={width} height={height} viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 4L4 12M4 4L12 12" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "checkmark-circle":
      return (
        <svg width={width} height={height} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="10" cy="10" r="10" fill="#fff" fillOpacity="0.15" />
          <path d="M6 10.5L9 13.5L14 8.5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "checkmark":
      return (
        <svg width={width} height={height} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M6 10.5L9 13.5L14 8.5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "circle-check-big":
      return (
        <svg
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          stroke={color || "currentColor"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M21.801 10A10 10 0 1 1 17 3.335" />
          <path d="m9 11 3 3L22 4" />
        </svg>
      );
    case "funnel":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox="0 0 24 24"
          fill="none"
          stroke={color || "currentColor"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          style={{ color: color || fill, width, height }}>
          <path d="M10 20a1 1 0 0 0 .553.895l2 1A1 1 0 0 0 14 21v-7a2 2 0 0 1 .517-1.341L21.74 4.67A1 1 0 0 0 21 3H3a1 1 0 0 0-.742 1.67l7.225 7.989A2 2 0 0 1 10 14z"></path>
        </svg>
      );
    case "folder-blue":
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M13.3333 13.3333C13.687 13.3333 14.0261 13.1929 14.2762 12.9428C14.5262 12.6928 14.6667 12.3536 14.6667 12V5.33333C14.6667 4.97971 14.5262 4.64057 14.2762 4.39052C14.0261 4.14048 13.687 4 13.3333 4H8.06668C7.84369 4.00219 7.62371 3.94841 7.42688 3.84359C7.23005 3.73877 7.06265 3.58625 6.94001 3.4L6.40001 2.6C6.2786 2.41565 6.11333 2.26432 5.91901 2.1596C5.72469 2.05488 5.50742 2.00004 5.28668 2H2.66668C2.31305 2 1.97392 2.14048 1.72387 2.39052C1.47382 2.64057 1.33334 2.97971 1.33334 3.33333V12C1.33334 12.3536 1.47382 12.6928 1.72387 12.9428C1.97392 13.1929 2.31305 13.3333 2.66668 13.3333H13.3333Z"
            stroke={color || "#1a1a1a"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "file-pdf":
      return (
        <svg width={width || 20} height={height || 20} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M12.5 1.66602H4.99998C4.55795 1.66602 4.13403 1.84161 3.82147 2.15417C3.50891 2.46673 3.33331 2.89065 3.33331 3.33268V16.666C3.33331 17.108 3.50891 17.532 3.82147 17.8445C4.13403 18.1571 4.55795 18.3327 4.99998 18.3327H15C15.442 18.3327 15.8659 18.1571 16.1785 17.8445C16.4911 17.532 16.6666 17.108 16.6666 16.666V5.83268L12.5 1.66602Z"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M11.6667 1.66602V4.99935C11.6667 5.44138 11.8423 5.8653 12.1548 6.17786C12.4674 6.49042 12.8913 6.66602 13.3334 6.66602H16.6667"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M8.33335 7.5H6.66669" stroke={color || "#0073CF"} strokeWidth="1.66667" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M13.3334 10.834H6.66669" stroke={color || "#0073CF"} strokeWidth="1.66667" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M13.3334 14.166H6.66669" stroke={color || "#0073CF"} strokeWidth="1.66667" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "file-csv":
      return (
        <svg width={width || 20} height={height || 20} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M12.5 1.66602H4.99998C4.55795 1.66602 4.13403 1.84161 3.82147 2.15417C3.50891 2.46673 3.33331 2.89065 3.33331 3.33268V16.666C3.33331 17.108 3.50891 17.532 3.82147 17.8445C4.13403 18.1571 4.55795 18.3327 4.99998 18.3327H15C15.442 18.3327 15.8659 18.1571 16.1785 17.8445C16.4911 17.532 16.6666 17.108 16.6666 16.666V5.83268L12.5 1.66602Z"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M11.6667 1.66602V4.99935C11.6667 5.44138 11.8423 5.8653 12.1548 6.17786C12.4674 6.49042 12.8913 6.66602 13.3334 6.66602H16.6667"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M6.66669 10.834H8.33335" stroke={color || "#0073CF"} strokeWidth="1.66667" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M11.6667 10.834H13.3334" stroke={color || "#0073CF"} strokeWidth="1.66667" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M6.66669 14.166H8.33335" stroke={color || "#0073CF"} strokeWidth="1.66667" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M11.6667 14.166H13.3334" stroke={color || "#0073CF"} strokeWidth="1.66667" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "file-image":
      return (
        <svg width={width || 20} height={height || 20} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M15.8333 2.5H4.16667C3.24619 2.5 2.5 3.24619 2.5 4.16667V15.8333C2.5 16.7538 3.24619 17.5 4.16667 17.5H15.8333C16.7538 17.5 17.5 16.7538 17.5 15.8333V4.16667C17.5 3.24619 16.7538 2.5 15.8333 2.5Z"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M7.49998 9.16732C8.42045 9.16732 9.16665 8.42113 9.16665 7.50065C9.16665 6.58018 8.42045 5.83398 7.49998 5.83398C6.57951 5.83398 5.83331 6.58018 5.83331 7.50065C5.83331 8.42113 6.57951 9.16732 7.49998 9.16732Z"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M17.5 12.4991L14.9283 9.92743C14.6158 9.61498 14.1919 9.43945 13.75 9.43945C13.3081 9.43945 12.8842 9.61498 12.5717 9.92743L5 17.4991"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "file-default":
      return (
        <svg width={width || 20} height={height || 20} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M12.5 1.66602H4.99998C4.55795 1.66602 4.13403 1.84161 3.82147 2.15417C3.50891 2.46673 3.33331 2.89065 3.33331 3.33268V16.666C3.33331 17.108 3.50891 17.532 3.82147 17.8445C4.13403 18.1571 4.55795 18.3327 4.99998 18.3327H15C15.442 18.3327 15.8659 18.1571 16.1785 17.8445C16.4911 17.532 16.6666 17.108 16.6666 16.666V5.83268L12.5 1.66602Z"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M11.6667 1.66602V4.99935C11.6667 5.44138 11.8423 5.8653 12.1548 6.17786C12.4674 6.49042 12.8913 6.66602 13.3334 6.66602H16.6667"
            stroke={color || "#0073CF"}
            strokeWidth="1.66667"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "download-file":
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M8 10V2" stroke={color || "#6B7280"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path
            d="M14 10V12.6667C14 13.0203 13.8595 13.3594 13.6095 13.6095C13.3594 13.8595 13.0203 14 12.6667 14H3.33333C2.97971 14 2.64057 13.8595 2.39052 13.6095C2.14048 13.3594 2 13.0203 2 12.6667V10"
            stroke={color || "#6B7280"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path d="M4.66663 6.66602L7.99996 9.99935L11.3333 6.66602" stroke={color || "#6B7280"} strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "selection-options":
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="4" y1="9" x2="16" y2="9"></line>
          <line x1="8" y1="15" x2="20" y2="15"></line>
          <circle cx="18" cy="9" r="2"></circle>
          <circle cx="6" cy="15" r="2"></circle>
        </svg>
      );
    case "upload":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 18}
          height={height || 18}
          viewBox="0 0 24 24"
          fill="none"
          stroke={color || "currentColor"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
          <polyline points="17 8 12 3 7 8"></polyline>
          <line x1="12" x2="12" y1="3" y2="15"></line>
        </svg>
      );
    case "at-sign":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 16}
          height={height || 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <circle cx="12" cy="12" r="4"></circle>
          <path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"></path>
        </svg>
      );
    case "send-message":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 16}
          height={height || 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"></path>
          <path d="m21.854 2.147-10.94 10.939"></path>
        </svg>
      );
    case "stop-recording":
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="5" y="5" width="10" height="10" rx="2" fill="currentColor" />
        </svg>
      );
    case "knowledge-base":
      return (
        <svg width={width || 64} height={height || 64} viewBox="10 15 40 30" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ width, height, color }}>
          <circle cx="32" cy="18" r="5.5" fill="currentColor" />
          <path
            d="M16 32
            C16 28, 24 28, 32 32
            C40 28, 48 28, 48 32
            V48
            C48 44, 40 44, 32 48
            C24 44, 16 44, 16 48
            V32Z"
            stroke="currentColor"
            strokeWidth="2"
            fill="none"
          />
          <line x1="32" y1="32" x2="32" y2="48" stroke="currentColor" strokeWidth="1.5" />
          <line x1="19" y1="33" x2="19" y2="47" stroke="currentColor" strokeWidth="0.8" />
          <line x1="22" y1="34" x2="22" y2="46" stroke="currentColor" strokeWidth="0.8" />
          <line x1="25" y1="35" x2="25" y2="45" stroke="currentColor" strokeWidth="0.8" />
          <line x1="28" y1="36" x2="28" y2="44" stroke="currentColor" strokeWidth="0.8" />
          <line x1="36" y1="36" x2="36" y2="44" stroke="currentColor" strokeWidth="0.8" />
          <line x1="39" y1="35" x2="39" y2="45" stroke="currentColor" strokeWidth="0.8" />
          <line x1="42" y1="34" x2="42" y2="46" stroke="currentColor" strokeWidth="0.8" />
          <line x1="45" y1="33" x2="45" y2="47" stroke="currentColor" strokeWidth="0.8" />
          <path d="M19 33C19 33 25 31 32 33C39 31 45 33 45 33" stroke="currentColor" strokeWidth="1" />
        </svg>
      );
    case "search-knowledge":
      return (
        <svg width={width || 18} height={height || 18} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
          <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "history":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 24}
          height={height || 24}
          viewBox="0 0 24 24"
          fill="none"
          stroke={stroke || color || "currentColor"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
          <path d="M3 3v5h5"></path>
          <path d="M12 7v5l4 2"></path>
        </svg>
      );
    case "filter-funnel":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 16}
          height={height || 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke={stroke || color || "currentColor"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M10 20a1 1 0 0 0 .553.895l2 1A1 1 0 0 0 14 21v-7a2 2 0 0 1 .517-1.341L21.74 4.67A1 1 0 0 0 21 3H3a1 1 0 0 0-.742 1.67l7.225 7.989A2 2 0 0 1 10 14z"></path>
        </svg>
      );
    case "chat-bubble":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 12}
          height={height || 12}
          viewBox="0 0 24 24"
          fill="none"
          stroke={stroke || color || "currentColor"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"></path>
        </svg>
      );
    case "trash-outline":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 16}
          height={height || 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke={stroke || color || "currentColor"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M3 6h18"></path>
          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
          <line x1="10" y1="11" x2="10" y2="17"></line>
          <line x1="14" y1="11" x2="14" y2="17"></line>
        </svg>
      );
    case "plan-header-icon":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 20}
          height={height || 20}
          viewBox="0 0 20 20"
          fill="none"
          stroke={stroke || color || "#0073CF"}
          strokeWidth="1.66667"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M10 15.0003V4.16699" />
          <path d="M12.5 10.8333C11.779 10.6226 11.1457 10.1839 10.695 9.58292C10.2443 8.98198 10.0005 8.25117 10 7.5C9.99955 8.25117 9.7557 8.98198 9.305 9.58292C8.8543 10.1839 8.221 10.6226 7.5 10.8333" />
          <path d="M14.665 5.4171C14.8568 5.08501 14.9695 4.71325 14.9946 4.3306C15.0197 3.94794 14.9565 3.56464 14.8097 3.21035C14.663 2.85605 14.4367 2.54027 14.1484 2.28742C13.8601 2.03457 13.5175 1.85143 13.1471 1.75218C12.7766 1.65293 12.3884 1.64022 12.0123 1.71503C11.6361 1.78985 11.2823 1.95019 10.9781 2.18364C10.6738 2.41709 10.4274 2.71741 10.2578 3.06134C10.0882 3.40528 9.99998 3.78362 10 4.1671C10 3.78362 9.91181 3.40528 9.74222 3.06134C9.57262 2.71741 9.32617 2.41709 9.02194 2.18364C8.71771 1.95019 8.36386 1.78985 7.98775 1.71503C7.61164 1.64022 7.22336 1.65293 6.85294 1.75218C6.48253 1.85143 6.13992 2.03457 5.85161 2.28742C5.5633 2.54027 5.33702 2.85605 5.19028 3.21035C5.04353 3.56464 4.98026 3.94794 5.00536 4.3306C5.03046 4.71325 5.14324 5.08501 5.335 5.4171" />
          <path d="M14.9971 4.27051C15.4869 4.39646 15.9417 4.63222 16.3269 4.95993C16.7121 5.28765 17.0177 5.69874 17.2205 6.16205C17.4234 6.62536 17.5181 7.12875 17.4976 7.6341C17.4771 8.13945 17.3418 8.6335 17.1021 9.07884" />
          <path d="M15 15.0003C15.7338 15.0002 16.447 14.7581 17.0291 14.3114C17.6112 13.8647 18.0297 13.2384 18.2196 12.5297C18.4095 11.8209 18.3603 11.0693 18.0795 10.3914C17.7987 9.7135 17.3021 9.14718 16.6667 8.78027" />
          <path d="M16.6388 14.5693C16.6972 15.0212 16.6624 15.4802 16.5364 15.9181C16.4105 16.356 16.1961 16.7634 15.9065 17.1151C15.6169 17.4669 15.2583 17.7556 14.8528 17.9633C14.4473 18.171 14.0035 18.2934 13.5489 18.3229C13.0942 18.3525 12.6383 18.2884 12.2094 18.1348C11.7804 17.9813 11.3875 17.7414 11.0549 17.43C10.7223 17.1186 10.457 16.7423 10.2755 16.3244C10.094 15.9065 10.0002 15.4558 9.99967 15.0002C9.99919 15.4558 9.9053 15.9065 9.72381 16.3244C9.54232 16.7423 9.27708 17.1186 8.94447 17.43C8.61186 17.7414 8.21895 17.9813 7.79 18.1348C7.36104 18.2884 6.90515 18.3525 6.45049 18.3229C5.99582 18.2934 5.55203 18.171 5.14652 17.9633C4.74101 17.7556 4.3824 17.4669 4.09283 17.1151C3.80325 16.7634 3.58887 16.356 3.46291 15.9181C3.33696 15.4802 3.3021 15.0212 3.36051 14.5693" />
          <path d="M5.00018 15.0003C4.26643 15.0002 3.55319 14.7581 2.97107 14.3114C2.38895 13.8647 1.97049 13.2384 1.78058 12.5297C1.59067 11.8209 1.63992 11.0693 1.92069 10.3914C2.20147 9.7135 2.69808 9.14718 3.33351 8.78027" />
          <path d="M5.00228 4.27051C4.51245 4.39646 4.0577 4.63222 3.67247 4.95993C3.28725 5.28765 2.98164 5.69874 2.77882 6.16205C2.57599 6.62536 2.48125 7.12875 2.50177 7.6341C2.52229 8.13945 2.65754 8.6335 2.89728 9.07884" />
        </svg>
      );
    case "thumbs-up-2":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 15}
          height={height || 15}
          viewBox="0 0 15 15"
          fill="none"
          stroke={stroke || color || "white"}
          strokeWidth="1.33333"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M9.33366 3.25366L8.66699 6.00033H12.5537C12.7607 6.00033 12.9648 6.04852 13.1499 6.14109C13.3351 6.23366 13.4961 6.36806 13.6203 6.53366C13.7445 6.69925 13.8285 6.89149 13.8655 7.09514C13.9025 7.2988 13.8916 7.50828 13.8337 7.70699L12.2803 13.0403C12.1995 13.3173 12.0311 13.5606 11.8003 13.7337C11.5695 13.9068 11.2888 14.0003 11.0003 14.0003H2.00033C1.6467 14.0003 1.30756 13.8598 1.05752 13.6098C0.807468 13.3598 0.666992 13.0206 0.666992 12.667V7.33366C0.666992 6.98004 0.807468 6.6409 1.05752 6.39085C1.30756 6.1408 1.6467 6.00033 2.00033 6.00033H3.84033C4.08838 6.00019 4.33148 5.93087 4.5423 5.80014C4.75311 5.66941 4.92327 5.48247 5.03366 5.26033L7.33366 0.666992C7.64804 0.670885 7.95748 0.745772 8.23886 0.886056C8.52024 1.02634 8.76628 1.2284 8.9586 1.47713C9.15091 1.72586 9.28454 2.01483 9.34948 2.32246C9.41443 2.63009 9.40902 2.94842 9.33366 3.25366Z" />
        </svg>
      );
    case "thumbs-down-2":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 15}
          height={height || 15}
          viewBox="0 0 15 15"
          fill="none"
          stroke={stroke || color || "#1A1A1A"}
          strokeWidth="1.33333"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M5.22033 11.4137L5.88699 8.66699H2.00033C1.79333 8.66699 1.58918 8.6188 1.40404 8.52623C1.2189 8.43366 1.05785 8.29925 0.933659 8.13366C0.809463 7.96806 0.725527 7.77583 0.688499 7.57217C0.651471 7.36852 0.662367 7.15904 0.720326 6.96032L2.27366 1.62699C2.35444 1.35004 2.52286 1.10676 2.75366 0.933659C2.98445 0.760563 3.26517 0.666992 3.55366 0.666992H12.5537C12.9073 0.666992 13.2464 0.807468 13.4965 1.05752C13.7465 1.30756 13.887 1.6467 13.887 2.00033V7.33366C13.887 7.68728 13.7465 8.02642 13.4965 8.27647C13.2464 8.52652 12.9073 8.66699 12.5537 8.66699H10.7137C10.4656 8.66712 10.2225 8.73645 10.0117 8.86718C9.80088 8.99791 9.63071 9.18485 9.52033 9.40699L7.22033 14.0003C6.90594 13.9964 6.5965 13.9215 6.31512 13.7813C6.03375 13.641 5.78771 13.4389 5.59539 13.1902C5.40307 12.9415 5.26945 12.6525 5.2045 12.3449C5.13955 12.0372 5.14496 11.7189 5.22033 11.4137Z" />
        </svg>
      );
    case "step-completed":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width={width || 14} height={height || 14} viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" fill={fill || "#2196F3"} />
          <path d="M8 12l3 3 5-5" stroke={stroke || "white"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "step-spinner":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width={width || 14} height={height || 14} viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke={stroke || color || "#2196F3"} strokeWidth="2" strokeDasharray="40" strokeDashoffset="10" />
        </svg>
      );
    case "close-small":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 16}
          height={height || 16}
          viewBox="0 0 20 20"
          fill="none"
          stroke={stroke || color || "currentColor"}
          strokeWidth="1.5"
          strokeLinecap="round">
          <path d="M6 6L14 14M14 6L6 14" />
        </svg>
      );
    case "history-clock":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 18}
          height={height || 18}
          viewBox="0 0 20 20"
          fill="none"
          stroke={stroke || color || "currentColor"}
          strokeWidth="1.5"
          strokeLinecap="round">
          <circle cx="10" cy="10" r="7" fill="none" />
          <path d="M10 6V10L13 12" />
        </svg>
      );
    case "star-outline":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 18}
          height={height || 18}
          viewBox="0 0 20 20"
          fill="none"
          stroke={stroke || color || "currentColor"}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M10 2L11.5 7H16.5L12.5 10L14 15L10 12L6 15L7.5 10L3.5 7H8.5L10 2Z" />
        </svg>
      );
    case "activity-pulse":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 19}
          height={height || 19}
          viewBox="0 0 19 19"
          fill="none"
          stroke={stroke || color || "#0073CF"}
          strokeWidth="1.66667"
          strokeLinecap="round"
          strokeLinejoin="round">
          <path d="M17.4997 9.16634H15.433C15.0688 9.16556 14.7144 9.2841 14.4239 9.50381C14.1335 9.72353 13.923 10.0323 13.8247 10.383L11.8663 17.3497C11.8537 17.3929 11.8274 17.431 11.7913 17.458C11.7553 17.4851 11.7114 17.4997 11.6663 17.4997C11.6213 17.4997 11.5774 17.4851 11.5413 17.458C11.5053 17.431 11.479 17.3929 11.4663 17.3497L6.86634 0.983008C6.85372 0.939734 6.8274 0.901721 6.79134 0.874674C6.75528 0.847628 6.71142 0.833008 6.66634 0.833008C6.62126 0.833008 6.5774 0.847628 6.54134 0.874674C6.50528 0.901721 6.47896 0.939734 6.46634 0.983008L4.50801 7.94967C4.41006 8.29897 4.20083 8.60677 3.91206 8.82635C3.6233 9.04593 3.27077 9.1653 2.90801 9.16634H0.833008" />
        </svg>
      );
    case "download-arrow":
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M10 13V3M7 10L10 13L13 10M5 17H15" stroke={stroke || color || "#666"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "check-success":
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M16 6L8.5 14.5L4 10" stroke={stroke || color || "#22c55e"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "copy":
      return (
        <svg
          width={width || 14}
          height={height || 14}
          viewBox="0 0 24 24"
          fill="none"
          stroke={stroke || color || "#666"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          xmlns="http://www.w3.org/2000/svg">
          <rect width="14" height="14" x="8" y="8" rx="2" ry="2"></rect>
          <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path>
        </svg>
      );
    case "canvas-grid":
      return (
        <svg width={width || 18} height={height || 18} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="3" y="3" width="7" height="7" rx="1" stroke={stroke || color || "#0073CF"} strokeWidth="2" />
          <rect x="14" y="3" width="7" height="7" rx="1" stroke={stroke || color || "#0073CF"} strokeWidth="2" />
          <rect x="3" y="14" width="7" height="7" rx="1" stroke={stroke || color || "#0073CF"} strokeWidth="2" />
          <rect x="14" y="14" width="7" height="7" rx="1" stroke={stroke || color || "#0073CF"} strokeWidth="2" />
        </svg>
      );
    case "fullscreen-expand":
      return (
        <svg width={width || 14} height={height || 14} viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M2 5L2 2L5 2" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M12 5L12 2L9 2" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M12 9L12 12L9 12" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M2 9L2 12L5 12" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "fullscreen-collapse":
      return (
        <svg width={width || 14} height={height || 14} viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M9 5L5 5L5 9" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M5 5L9 9" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "close-canvas":
      return (
        <svg width={width || 14} height={height || 14} viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M11 3L3 11M3 3L11 11" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "step-checkmark":
      // Blue filled circle with white checkmark - used in reasoning steps
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="10" cy="10" r="10" fill={fill || "#0073CF"} />
          <path d="M6 10L9 13L14 7" stroke={stroke || "white"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "execution-steps":
      // Circle with checkmark outline - used for execution steps button
      return (
        <svg width={width || 20} height={height || 20} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="12" cy="12" r="9" stroke={stroke || color || "#6B7280"} strokeWidth="1.5" />
          <path d="M8 12l3 3 5-5" stroke={stroke || color || "#6B7280"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "chevron-down-sm":
      // Small chevron down for accordion toggles
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" style={props.style}>
          <path d="M6 8L10 12L14 8" stroke={stroke || color || "currentColor"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "view-details-eye":
      // Eye icon for view details button
      return (
        <svg width={width || 18} height={height || 18} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke={stroke || color || "#6B7280"} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="12" cy="12" r="3" stroke={stroke || color || "#6B7280"} strokeWidth="1.5" />
        </svg>
      );
    case "light-icon":
      return (
        <svg width={width || 16} height={height || 16} viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M13.9899 8.32394C13.9275 9.48137 13.5311 10.5959 12.8487 11.5329C12.1662 12.4698 11.2271 13.1891 10.1446 13.6036C9.06217 14.0182 7.88282 14.1104 6.74912 13.869C5.61542 13.6276 4.5759 13.063 3.75624 12.2434C2.93658 11.4238 2.37186 10.3844 2.13035 9.25068C1.88883 8.117 1.98087 6.93764 2.39532 5.85515C2.80977 4.77266 3.52891 3.8334 4.46579 3.1509C5.40266 2.4684 6.51718 2.07188 7.6746 2.00927C7.9446 1.99461 8.08594 2.31594 7.9426 2.54461C7.4632 3.31164 7.25792 4.21852 7.36027 5.11724C7.46262 6.01596 7.86655 6.85346 8.50615 7.49306C9.14575 8.13266 9.98325 8.53659 10.882 8.63894C11.7807 8.74129 12.6876 8.53601 13.4546 8.05661C13.6839 7.91327 14.0046 8.05394 13.9899 8.32394Z"
            stroke={stroke || color || "#6B7280"}
            strokeWidth="1.33333"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "dark-icon":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width || 16}
          height={height || 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <circle cx="12" cy="12" r="4"></circle>
          <path d="M12 2v2"></path>
          <path d="M12 20v2"></path>
          <path d="m4.93 4.93 1.41 1.41"></path>
          <path d="m17.66 17.66 1.41 1.41"></path>
          <path d="M2 12h2"></path>
          <path d="M20 12h2"></path>
          <path d="m6.34 17.66-1.41 1.41"></path>
          <path d="m19.07 4.93-1.41 1.41"></path>
        </svg>
      );
    case "logout":
      return (
        <svg width={width || "16"} height={height || "16"} viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 12.75L15.75 9L12 5.25" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M15.75 9H6.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path
            d="M6.75 15.75H3.75C3.35218 15.75 2.97064 15.592 2.68934 15.3107C2.40804 15.0294 2.25 14.6478 2.25 14.25V3.75C2.25 3.35218 2.40804 2.97064 2.68934 2.68934C2.97064 2.40804 3.35218 2.25 3.75 2.25H6.75"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "fa-project-diagram":
      return (
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ width, height, color, transform: "rotate(90deg)" }}>
          {/* Top-left box */}
          <rect x="1" y="2" width="4" height="4" rx="0.75" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          {/* Top-right box */}
          <rect x="11" y="2" width="4" height="4" rx="0.75" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          {/* Bottom-center box */}
          <rect x="6" y="10" width="4" height="4" rx="0.75" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          {/* Connecting lines */}
          <path d="M5 4H11" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M3 6V8H8V10" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M13 6V8H8" stroke="currentColor" strokeWidth="1.33333" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    default:
      return <></>;
  }
};

export default SVGIcons;
