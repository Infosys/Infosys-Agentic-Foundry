import React from "react";

const SVGIcons = (props) => {
  const {
    icon,
    width = 20,
    height = 20,
    fill = "#FFFFFF",
    color = "#FFFFFF",
  } = props;
  const svgStyle = {
    width,
    height,
    fill,
    color,
  };
  switch (icon) {
    case "fa-solid fa-user-xmark":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 640 512"
          {...svgStyle}
        >
          <path d="M96 128a128 128 0 1 1 256 0A128 128 0 1 1 96 128zM0 482.3C0 383.8 79.8 304 178.3 304l91.4 0C368.2 304 448 383.8 448 482.3c0 16.4-13.3 29.7-29.7 29.7L29.7 512C13.3 512 0 498.7 0 482.3zM471 143c9.4-9.4 24.6-9.4 33.9 0l47 47 47-47c9.4-9.4 24.6-9.4 33.9 0s9.4 24.6 0 33.9l-47 47 47 47c9.4 9.4 9.4 24.6 0 33.9s-24.6 9.4-33.9 0l-47-47-47 47c-9.4 9.4-24.6 9.4-33.9 0s-9.4-24.6 0-33.9l47-47-47-47c-9.4-9.4-9.4-24.6 0-33.9z" />
        </svg>
      );
    case "fa-solid fa-pen":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path d="M362.7 19.3L314.3 67.7 444.3 197.7l48.4-48.4c25-25 25-65.5 0-90.5L453.3 19.3c-25-25-65.5-25-90.5 0zm-71 71L58.6 323.5c-10.4 10.4-18 23.3-22.2 37.4L1 481.2C-1.5 489.7 .8 498.8 7 505s15.3 8.5 23.7 6.1l120.3-35.4c14.1-4.2 27-11.8 37.4-22.2L421.7 220.3 291.7 90.3z" />
        </svg>
      );
    case "ionic-ios-send":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="ionicon"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path d="M476.59 227.05l-.16-.07L49.35 49.84A23.56 23.56 0 0027.14 52 24.65 24.65 0 0016 72.59v113.29a24 24 0 0019.52 23.57l232.93 43.07a4 4 0 010 7.86L35.53 303.45A24 24 0 0016 327v113.31A23.57 23.57 0 0026.59 460a23.94 23.94 0 0013.22 4 24.55 24.55 0 009.52-1.93L476.4 285.94l.19-.09a32 32 0 000-58.8z" />
        </svg>
      );
    case "hardware-chip":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="ionicon"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
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
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="ionicon"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path d="M256 48C141.31 48 48 141.31 48 256s93.31 208 208 208 208-93.31 208-208S370.69 48 256 48zm-50.22 116.82C218.45 151.39 236.28 144 256 144s37.39 7.44 50.11 20.94c12.89 13.68 19.16 32.06 17.68 51.82C320.83 256 290.43 288 256 288s-64.89-32-67.79-71.25c-1.47-19.92 4.79-38.36 17.57-51.93zM256 432a175.49 175.49 0 01-126-53.22 122.91 122.91 0 0135.14-33.44C190.63 329 222.89 320 256 320s65.37 9 90.83 25.34A122.87 122.87 0 01382 378.78 175.45 175.45 0 01256 432z" />
        </svg>
      );
    case "close-icon":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="ionicon"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="32"
            d="M368 368L144 144M368 144L144 368"
          />
        </svg>
      );
    case "fa-user-plus":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 640 512"
          {...svgStyle}
        >
          <path d="M96 128a128 128 0 1 1 256 0A128 128 0 1 1 96 128zM0 482.3C0 383.8 79.8 304 178.3 304l91.4 0C368.2 304 448 383.8 448 482.3c0 16.4-13.3 29.7-29.7 29.7L29.7 512C13.3 512 0 498.7 0 482.3zM504 312l0-64-64 0c-13.3 0-24-10.7-24-24s10.7-24 24-24l64 0 0-64c0-13.3 10.7-24 24-24s24 10.7 24 24l0 64 64 0c13.3 0 24 10.7 24 24s-10.7 24-24 24l-64 0 0 64c0 13.3-10.7 24-24 24s-24-10.7-24-24z" />
        </svg>
      );
    case "fa-user-check":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 640 512"
          {...svgStyle}
        >
          <path d="M96 128a128 128 0 1 1 256 0A128 128 0 1 1 96 128zM0 482.3C0 383.8 79.8 304 178.3 304l91.4 0C368.2 304 448 383.8 448 482.3c0 16.4-13.3 29.7-29.7 29.7L29.7 512C13.3 512 0 498.7 0 482.3zM625 177L497 305c-9.4 9.4-24.6 9.4-33.9 0l-64-64c-9.4-9.4-9.4-24.6 0-33.9s24.6-9.4 33.9 0l47 47L591 143c9.4-9.4 24.6-9.4 33.9 0s9.4 24.6 0 33.9z" />
        </svg>
      );
    case "fa-screwdriver-wrench":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path d="M78.6 5C69.1-2.4 55.6-1.5 47 7L7 47c-8.5 8.5-9.4 22-2.1 31.6l80 104c4.5 5.9 11.6 9.4 19 9.4l54.1 0 109 109c-14.7 29-10 65.4 14.3 89.6l112 112c12.5 12.5 32.8 12.5 45.3 0l64-64c12.5-12.5 12.5-32.8 0-45.3l-112-112c-24.2-24.2-60.6-29-89.6-14.3l-109-109 0-54.1c0-7.5-3.5-14.5-9.4-19L78.6 5zM19.9 396.1C7.2 408.8 0 426.1 0 444.1C0 481.6 30.4 512 67.9 512c18 0 35.3-7.2 48-19.9L233.7 374.3c-7.8-20.9-9-43.6-3.6-65.1l-61.7-61.7L19.9 396.1zM512 144c0-10.5-1.1-20.7-3.2-30.5c-2.4-11.2-16.1-14.1-24.2-6l-63.9 63.9c-3 3-7.1 4.7-11.3 4.7L352 176c-8.8 0-16-7.2-16-16l0-57.4c0-4.2 1.7-8.3 4.7-11.3l63.9-63.9c8.1-8.1 5.2-21.8-6-24.2C388.7 1.1 378.5 0 368 0C288.5 0 224 64.5 224 144l0 .8 85.3 85.3c36-9.1 75.8 .5 104 28.7L429 274.5c49-23 83-72.8 83-130.5zM56 432a24 24 0 1 1 48 0 24 24 0 1 1 -48 0z" />
        </svg>
      );
    case "fa-robot":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 640 512"
          {...svgStyle}
        >
          <path d="M320 0c17.7 0 32 14.3 32 32l0 64 120 0c39.8 0 72 32.2 72 72l0 272c0 39.8-32.2 72-72 72l-304 0c-39.8 0-72-32.2-72-72l0-272c0-39.8 32.2-72 72-72l120 0 0-64c0-17.7 14.3-32 32-32zM208 384c-8.8 0-16 7.2-16 16s7.2 16 16 16l32 0c8.8 0 16-7.2 16-16s-7.2-16-16-16l-32 0zm96 0c-8.8 0-16 7.2-16 16s7.2 16 16 16l32 0c8.8 0 16-7.2 16-16s-7.2-16-16-16l-32 0zm96 0c-8.8 0-16 7.2-16 16s7.2 16 16 16l32 0c8.8 0 16-7.2 16-16s-7.2-16-16-16l-32 0zM264 256a40 40 0 1 0 -80 0 40 40 0 1 0 80 0zm152 40a40 40 0 1 0 0-80 40 40 0 1 0 0 80zM48 224l16 0 0 192-16 0c-26.5 0-48-21.5-48-48l0-96c0-26.5 21.5-48 48-48zm544 0c26.5 0 48 21.5 48 48l0 96c0 26.5-21.5 48-48 48l-16 0 0-192 16 0z" />
        </svg>
      );
    case "nav-chat":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="800px"
          height="800px"
          viewBox="0 0 32 32"
          id="svg5"
          version="1.1"
          {...svgStyle}
        >
          <defs id="defs2" />

          <g id="layer1" transform="translate(-348,-292)">
            <path
              d="m 363,311.01367 a 1,1 0 0 0 -1,1 1,1 0 0 0 1,1 h 10 a 1,1 0 0 0 1,-1 1,1 0 0 0 -1,-1 z"
              id="path453479"
            />

            <path
              d="m 355,303.01367 a 1,1 0 0 0 -1,1 1,1 0 0 0 1,1 h 10 a 1,1 0 0 0 1,-1 1,1 0 0 0 -1,-1 z"
              id="path453465"
            />

            <path
              d="m 355,299.01367 a 1,1 0 0 0 -1,1 1,1 0 0 0 1,1 h 10 a 1,1 0 0 0 1,-1 1,1 0 0 0 -1,-1 z"
              id="path453451"
            />

            <path
              d="m 353,295.01367 c -1.64501,0 -3,1.35499 -3,3 v 14 c 0,0.66395 0.4382,1.24104 0.97852,1.46485 0.54031,0.2238 1.25903,0.12573 1.72851,-0.34375 a 1.0001,1.0001 0 0 0 0.0332,-0.0371 l 3.70313,-4.08399 H 358 v 5 c 0,1.64501 1.35499,3 3,3 h 10.55664 l 3.70313,4.08594 a 1.0001,1.0001 0 0 0 0.0332,0.0352 c 0.46943,0.46943 1.18816,0.56747 1.72851,0.34375 0.54036,-0.22373 0.97852,-0.8009 0.97852,-1.46485 v -14 c 0,-1.64501 -1.35499,-3 -3,-3 h -5 v -5 c 0,-1.64501 -1.35499,-3 -3,-3 z m 0,2 h 14 c 0.56413,0 1,0.43587 1,1 v 8 c 0,0.56413 -0.43587,1 -1,1 h -11 a 1.0001,1.0001 0 0 0 -0.74023,0.32813 L 352,310.93945 v -12.92578 c 0,-0.56413 0.43587,-1 1,-1 z m 17,8 h 5 c 0.56413,0 1,0.43587 1,1 v 12.92578 l -3.25977,-3.59765 A 1.0001,1.0001 0 0 0 372,315.01367 h -11 c -0.56413,0 -1,-0.43587 -1,-1 v -5 h 7 6 a 1,1 0 0 0 1,-1 1,1 0 0 0 -1,-1 h -3.17773 c 0.11257,-0.31368 0.17773,-0.64974 0.17773,-1 z"
              id="path453435"
            />
          </g>
        </svg>
      );
    case "new-chat":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="800px"
          height="800px"
          viewBox="0 0 24 24"
          {...svgStyle}
        >
          <path
            d="M12 2C6.48 2 2 5.58 2 10c0 2.39 1.39 4.53 3.54 6.03-.34 1.23-1.03 2.3-1.99 3.17-.2.18-.25.46-.13.7.12.24.37.38.63.38 1.52 0 3.04-.58 4.38-1.64C10.07 19.68 11.02 20 12 20c5.52 0 10-3.58 10-8s-4.48-8-10-8zm0 14c-.98 0-1.93-.32-2.74-.88-.2-.14-.47-.13-.66.02-1.06.84-2.3 1.34-3.6 1.47.56-.72.99-1.54 1.27-2.42.08-.26-.02-.54-.24-.7C4.4 12.9 3.5 11.5 3.5 10c0-3.31 3.58-6 8-6s8 2.69 8 6-3.58 6-8 6z"
          />
        </svg>
      );
    case "search":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="ionicon"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path
            d="M221.09 64a157.09 157.09 0 10157.09 157.09A157.1 157.1 0 00221.09 64z"
            fill="none"
            stroke="currentColor"
            strokeMiterlimit="10"
            strokeWidth="32"
          />
          <path
            fill="none"
            stroke="currentColor"
            strokeLinecap="round"
            strokeMiterlimit="10"
            strokeWidth="32"
            d="M338.29 338.29L448 448"
          />
        </svg>
      );
    case "fa-question":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 320 512"
          {...svgStyle}
        >
          <path d="M80 160c0-35.3 28.7-64 64-64l32 0c35.3 0 64 28.7 64 64l0 3.6c0 21.8-11.1 42.1-29.4 53.8l-42.2 27.1c-25.2 16.2-40.4 44.1-40.4 74l0 1.4c0 17.7 14.3 32 32 32s32-14.3 32-32l0-1.4c0-8.2 4.2-15.8 11-20.2l42.2-27.1c36.6-23.6 58.8-64.1 58.8-107.7l0-3.6c0-70.7-57.3-128-128-128l-32 0C73.3 32 16 89.3 16 160c0 17.7 14.3 32 32 32s32-14.3 32-32zm80 320a40 40 0 1 0 0-80 40 40 0 1 0 0 80z" />
        </svg>
      );
    case "fa-user":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 448 512"
          {...svgStyle}
        >
          <path d="M224 256A128 128 0 1 0 224 0a128 128 0 1 0 0 256zm-45.7 48C79.8 304 0 383.8 0 482.3C0 498.7 13.3 512 29.7 512l388.6 0c16.4 0 29.7-13.3 29.7-29.7C448 383.8 368.2 304 269.7 304l-91.4 0z" />
        </svg>
      );
    case "slider-rect":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path d="M0 416c0 17.7 14.3 32 32 32l54.7 0c12.3 28.3 40.5 48 73.3 48s61-19.7 73.3-48L480 448c17.7 0 32-14.3 32-32s-14.3-32-32-32l-246.7 0c-12.3-28.3-40.5-48-73.3-48s-61 19.7-73.3 48L32 384c-17.7 0-32 14.3-32 32zm128 0a32 32 0 1 1 64 0 32 32 0 1 1 -64 0zM320 256a32 32 0 1 1 64 0 32 32 0 1 1 -64 0zm32-80c-32.8 0-61 19.7-73.3 48L32 224c-17.7 0-32 14.3-32 32s14.3 32 32 32l246.7 0c12.3 28.3 40.5 48 73.3 48s61-19.7 73.3-48l54.7 0c17.7 0 32-14.3 32-32s-14.3-32-32-32l-54.7 0c-12.3-28.3-40.5-48-73.3-48zM192 128a32 32 0 1 1 0-64 32 32 0 1 1 0 64zm73.3-64C253 35.7 224.8 16 192 16s-61 19.7-73.3 48L32 64C14.3 64 0 78.3 0 96s14.3 32 32 32l86.7 0c12.3 28.3 40.5 48 73.3 48s61-19.7 73.3-48L480 128c17.7 0 32-14.3 32-32s-14.3-32-32-32L265.3 64z" />
        </svg>
      );
    case "fa-plus":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 448 512"
          {...svgStyle}
        >
          <path d="M256 80c0-17.7-14.3-32-32-32s-32 14.3-32 32l0 144L48 224c-17.7 0-32 14.3-32 32s14.3 32 32 32l144 0 0 144c0 17.7 14.3 32 32 32s32-14.3 32-32l0-144 144 0c17.7 0 32-14.3 32-32s-14.3-32-32-32l-144 0 0-144z" />
        </svg>
      );
    case "fa-trash":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 448 512"
          {...svgStyle}
        >
          <path d="M135.2 17.7L128 32 32 32C14.3 32 0 46.3 0 64S14.3 96 32 96l384 0c17.7 0 32-14.3 32-32s-14.3-32-32-32l-96 0-7.2-14.3C307.4 6.8 296.3 0 284.2 0L163.8 0c-12.1 0-23.2 6.8-28.6 17.7zM416 128L32 128 53.2 467c1.6 25.3 22.6 45 47.9 45l245.8 0c25.3 0 46.3-19.7 47.9-45L416 128z" />
        </svg>
      );
    case "fa-xmark":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 384 512"
          {...svgStyle}
        >
          <path d="M342.6 150.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L192 210.7 86.6 105.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3L146.7 256 41.4 361.4c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L192 301.3 297.4 406.6c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L237.3 256 342.6 150.6z" />
        </svg>
      );
    case "fa-circle-xmark":
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path d="M256 512A256 256 0 1 0 256 0a256 256 0 1 0 0 512zM175 175c9.4-9.4 24.6-9.4 33.9 0l47 47 47-47c9.4-9.4 24.6-9.4 33.9 0s9.4 24.6 0 33.9l-47 47 47 47c9.4 9.4 9.4 24.6 0 33.9s-24.6 9.4-33.9 0l-47-47-47 47c-9.4 9.4-24.6 9.4-33.9 0s-9.4-24.6 0-33.9l47-47-47-47c-9.4-9.4-9.4-24.6 0-33.9z" />
        </svg>
      );
    case "caret":
      return (
        <svg
          viewBox="0 0 24 24"
          xmlns="http://www.w3.org/2000/svg"
          {...svgStyle}
        >
          <path d="M16.59 8.59L12 13.17 7.41 8.59 6 10l6 6 6-6-1.41-1.41z"></path>
        </svg>
      );
    case "downarrow":
      return (
        <svg
          {...svgStyle}
          viewBox="0 -6 524 524"
          xmlns="http://www.w3.org/2000/svg"
        >
          <title>down</title>
          <path d="M64 191L98 157 262 320 426 157 460 191 262 387 64 191Z" />
        </svg>
      );
    case "rightarrow":
      return (
        <svg
          {...svgStyle}
          viewBox="-77 0 512 512"
          xmlns="http://www.w3.org/2000/svg"
        >
          <title>right</title>
          <path d="M98 460L64 426 227 262 64 98 98 64 294 262 98 460Z" />
        </svg>
      );
    case "info":
      return (
        <svg
          {...svgStyle}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 192 512"
        >
          <path d="M48 80a48 48 0 1 1 96 0A48 48 0 1 1 48 80zM0 224c0-17.7 14.3-32 32-32l64 0c17.7 0 32 14.3 32 32l0 224 32 0c17.7 0 32 14.3 32 32s-14.3 32-32 32L32 512c-17.7 0-32-14.3-32-32s14.3-32 32-32l32 0 0-192-32 0c-17.7 0-32-14.3-32-32z" />
        </svg>
      );
    case "exclamation":
      return (
        <svg
          {...svgStyle}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 128 512"
        >
          <path d="M96 64c0-17.7-14.3-32-32-32S32 46.3 32 64l0 256c0 17.7 14.3 32 32 32s32-14.3 32-32L96 64zM64 480a40 40 0 1 0 0-80 40 40 0 1 0 0 80z" />
        </svg>
      );
    case "check":
      return (
        <svg
          {...svgStyle}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 448 512"
        >
          <path d="M438.6 105.4c12.5 12.5 12.5 32.8 0 45.3l-256 256c-12.5 12.5-32.8 12.5-45.3 0l-128-128c-12.5-12.5-12.5-32.8 0-45.3s32.8-12.5 45.3 0L160 338.7 393.4 105.4c12.5-12.5 32.8-12.5 45.3 0z" />
        </svg>
      );
    case "download":
      return (
        <svg
          {...svgStyle}
          viewBox="0 0 24 24"
          xmlns="http://www.w3.org/2000/svg"
        >
          <title>down</title>
          <path d="M12 2C12.5523 2 13 2.44772 13 3V15.5858L16.2929 12.2929C16.6834 11.9024 17.3166 11.9024 17.7071 12.2929C18.0976 12.6834 18.0976 13.3166 17.7071 13.7071L12.7071 18.7071C12.3166 19.0976 11.6834 19.0976 11.2929 18.7071L6.29289 13.7071C5.90237 13.3166 5.90237 12.6834 6.29289 12.2929C6.68342 11.9024 7.31658 11.9024 7.70711 12.2929L11 15.5858V3C11 2.44772 11.4477 2 12 2ZM4 20C4 19.4477 4.44772 19 5 19H19C19.5523 19 20 19.4477 20 20C20 20.5523 19.5523 21 19 21H5C4.44772 21 4 20.5523 4 20Z" />
        </svg>
      );
    case "drop_arrow_down":
      return (
        <svg
          width={200}
          height={200}
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <g id="SVGRepo_bgCarrier" strokeWidth="0"></g>
          <g
            id="SVGRepo_tracerCarrier"
            strokeLinecap="round"
            strokeLinejoin="round"
          ></g>
          <g id="SVGRepo_iconCarrier">
            {" "}
            <path
              fill-rule="evenodd"
              clip-rule="evenodd"
              d="M12.7071 14.7071C12.3166 15.0976 11.6834 15.0976 11.2929 14.7071L6.29289 9.70711C5.90237 9.31658 5.90237 8.68342 6.29289 8.29289C6.68342 7.90237 7.31658 7.90237 7.70711 8.29289L12 12.5858L16.2929 8.29289C16.6834 7.90237 17.3166 7.90237 17.7071 8.29289C18.0976 8.68342 18.0976 9.31658 17.7071 9.70711L12.7071 14.7071Z"
              fill="#ffffff"
            ></path>{" "}
          </g>
        </svg>
      );
    case "drop_arrow_up":
      return (
        <svg
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          transform="rotate(180)"
          width={200}
          height={200}
        >
          <g id="SVGRepo_bgCarrier" strokeWidth="0"></g>
          <g
            id="SVGRepo_tracerCarrier"
            strokeLinecap="round"
            strokeLinejoin="round"
          ></g>
          <g id="SVGRepo_iconCarrier">
            {" "}
            <path
              fill-rule="evenodd"
              clip-rule="evenodd"
              d="M12.7071 14.7071C12.3166 15.0976 11.6834 15.0976 11.2929 14.7071L6.29289 9.70711C5.90237 9.31658 5.90237 8.68342 6.29289 8.29289C6.68342 7.90237 7.31658 7.90237 7.70711 8.29289L12 12.5858L16.2929 8.29289C16.6834 7.90237 17.3166 7.90237 17.7071 8.29289C18.0976 8.68342 18.0976 9.31658 17.7071 9.70711L12.7071 14.7071Z"
              fill="#ffffff"
            ></path>{" "}
          </g>
        </svg>
      );
    case "file":
      return (
        <svg
          {...svgStyle}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
        >
          <path d="M14 2H6C4.9 2 4 2.9 4 4V20C4 21.1 4.9 22 6 22H18C19.1 22 20 21.1 20 20V8L14 2ZM14 3.5L18.5 8H14V3.5ZM6 4H13V9H18V20H6V4Z" />
        </svg>
      );
    case "detail":
      return (
        <svg
          style={svgStyle}
          viewBox="0 0 16 16"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <g id="SVGRepo_bgCarrier" strokeWidth="0" />

          <g
            id="SVGRepo_tracerCarrier"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          <g id="SVGRepo_iconCarrier">
            {" "}
            <path d="M15 1H1V3H15V1Z" fill="#ffffff" />{" "}
            <path
              d="M11 5H1V7H6.52779C7.62643 5.7725 9.223 5 11 5Z"
              fill="#ffffff"
            />{" "}
            <path
              d="M5.34141 13C5.60482 13.7452 6.01127 14.4229 6.52779 15H1V13H5.34141Z"
              fill="#ffffff"
            />{" "}
            <path
              d="M5.34141 9C5.12031 9.62556 5 10.2987 5 11H1V9H5.34141Z"
              fill="#ffffff"
            />{" "}
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
            viewBox="0 0 384 512"
            {...svgStyle}
          >
            <path d="M224 0c35.3 0 64 28.7 64 64v32h56c30.9 0 56 25.1 56 56v304c0 30.9-25.1 56-56 56H152c-30.9 0-56-25.1-56-56v-32H40c-30.9 0-56-25.1-56-56V88c0-30.9 25.1-56 56-56H160V64c0-35.3 28.7-64 64-64zM160 64v32h128V64c0-17.7-14.3-32-32-32H192c-17.7 0-32 14.3-32 32zM40 88v304c0 13.3 10.7 24 24 24h56V64H64c-13.3 0-24 10.7-24 24zm304 328V112c0-13.3-10.7-24-24-24H152c-13.3 0-24 10.7-24 24v304c0 13.3 10.7 24 24 24h168c13.3 0 24-10.7 24-24z" />
          </svg>
        );
    case "eyeIcon":
      return (
        <svg
          {...svgStyle}
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <g id="SVGRepo_bgCarrier" strokeWidth="0" />

          <g
            id="SVGRepo_tracerCarrier"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

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
            {...svgStyle}
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
          >
            <path
              d="M12 5C7.455 5 3.734 7.943 2.46 12C3.734 16.057 7.455 19 12 19C16.545 19 20.266 16.057 21.54 12C20.266 7.943 16.545 5 12 5Z"
              stroke={svgStyle.fill}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <circle
              cx="12"
              cy="12"
              r="3"
              stroke={svgStyle.fill}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        );
        case "eye-slash":
          return (
            <svg
              {...svgStyle}
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
            >
              <path
                d="M3 3L21 21"
                stroke={svgStyle.fill}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
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
        <svg
          {...svgStyle}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
        >
          <rect x="3" y="13" width="4" height="8" rx="1" fill={svgStyle.fill} />
          <rect x="9" y="9" width="4" height="12" rx="1" fill={svgStyle.fill} />
          <rect x="15" y="5" width="4" height="16" rx="1" fill={svgStyle.fill} />
        </svg>
      );
    case "warnings":
      return (
        <svg
          {...svgStyle}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
        >
          <polygon points="12,3 2,21 22,21" fill="#FFD600" stroke="#B8860B" strokeWidth="1.5"/>
          <rect x="11" y="9" width="2" height="6" rx="1" fill="#B8860B"/>
          <circle cx="12" cy="18" r="1.2" fill="#B8860B"/>
        </svg>
      );
    case "tableIcon":
      return (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <rect x="3" y="3" width="18" height="18" rx="2" stroke="#007cc3" stroke-width="2" fill="none"/>
          <line x1="3" y1="9" x2="21" y2="9" stroke="#007cc3" stroke-width="2"/>
          <line x1="3" y1="15" x2="21" y2="15" stroke="#007cc3" stroke-width="2"/>
          <line x1="9" y1="3" x2="9" y2="21" stroke="#007cc3" stroke-width="2"/>
          <line x1="15" y1="3" x2="15" y2="21" stroke="#007cc3" stroke-width="2"/>
        </svg>
      );
    case "accordionIcon":
      return(
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <rect x="3" y="5" width="18" height="3" rx="1" fill="#007cc3"/>
          <rect x="3" y="10.5" width="18" height="3" rx="1" fill="#007cc3"/>
          <rect x="3" y="16" width="18" height="3" rx="1" fill="#007cc3"/>
          <polyline points="7,7 12,12 17,7" fill="none" stroke="#fff" stroke-width="2"/>
        </svg>
      );
    case "fa-solid fa-up-right-and-down-left-from-center":
      // FontAwesome expand icon (up-right-and-down-left-from-center)
      return (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 512 512"
          {...svgStyle}
        >
          <path d="M320 32c0-17.7 14.3-32 32-32h128c17.7 0 32 14.3 32 32v128c0 17.7-14.3 32-32 32s-32-14.3-32-32V83.3L329 234.3c-12.5 12.5-32.8 12.5-45.3 0s-12.5-32.8 0-45.3L434.7 64H352c-17.7 0-32-14.3-32-32zM192 480c0 17.7-14.3 32-32 32H32c-17.7 0-32-14.3-32-32V352c0-17.7 14.3-32 32-32s32 14.3 32 32v44.7L183 277.7c12.5-12.5 32.8-12.5 45.3 0s12.5 32.8 0 45.3L77.3 448H160c17.7 0 32 14.3 32 32z" />
        </svg>
      );
case "ground-truth":
  return (
    <svg {...svgStyle} viewBox="0 0 24 24" fill="none">
      <rect 
        x="1" 
        y="18.5" 
        width="22" 
        height="2.5" 
        fill="currentColor"
        rx="1.2"
      />
      <path 
        d="M12 2L5 4.5V11.5C5 15.5 8 18.8 12 19.8C16 18.8 19 15.5 19 11.5V4.5L12 2Z" 
        fill="#343741"
        fillOpacity="0.2"
      />
      <path 
        d="M12 2L5 4.5V11.5C5 15.5 8 18.8 12 19.8C16 18.8 19 15.5 19 11.5V4.5L12 2Z" 
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <path 
        d="M8.5 11.5L11 14L15.5 9.5" 
        stroke="currentColor"
        strokeWidth="3" 
        strokeLinecap="round" 
        strokeLinejoin="round"
      />
    </svg>
      );
    default:
      return <></>;
  }
};

export default SVGIcons;
