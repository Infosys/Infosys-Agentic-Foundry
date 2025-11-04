import React, { useState, useRef, useEffect } from "react";
import styles from "../../css_modules/NewCommonDropdown.module.css";

const NewCommonDropdown = ({
  options = [],
  selected = "",
  onSelect = () => {},
  placeholder = "Select...",
  width = 240,
  disabled = false,
}) => {
  const [open, setOpen] = useState(false);
  const [highlighted, setHighlighted] = useState(-1);
  const [search, setSearch] = useState("");
  const [direction, setDirection] = useState("down"); // 'down' or 'up'
  const listRef = useRef(null);
  const optionRefs = useRef([]);
  const inputRef = useRef(null);

  const filteredOptions = options
    .filter(opt => !search || opt.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => a.localeCompare(b));

  const checkDropdownDirection = () => {
    const input = inputRef.current;
    if (!input) return "down";
    const rect = input.getBoundingClientRect();
    const windowHeight = window.innerHeight;
    const spaceBelow = windowHeight - rect.bottom;
    const spaceAbove = rect.top;
    // 200px is approx dropdown height
    if (spaceBelow < 200 && spaceAbove > spaceBelow) return "up";
    return "down";
  };

  useEffect(() => {
    if (open) {
      setDirection(checkDropdownDirection());
    }
  }, [open]);

  useEffect(() => {
    if (open && highlighted >= 0 && optionRefs.current[highlighted]) {
      const option = optionRefs.current[highlighted];
      const list = listRef.current;
      if (option && list) {
        const optionTop = option.offsetTop;
        const optionBottom = optionTop + option.offsetHeight;
        const listTop = list.scrollTop;
        const listBottom = listTop + list.offsetHeight;
        if (optionTop < listTop) {
          list.scrollTop = optionTop;
        } else if (optionBottom > listBottom) {
          list.scrollTop = optionBottom - list.offsetHeight;
        }
      }
    }
  }, [highlighted, open, options.length]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (listRef.current && !listRef.current.contains(e.target)) {
        setOpen(false);
        setHighlighted(-1);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open]);

  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);

  const handleKeyDown = (e) => {
    if (!open) return;
    if (e.key === "ArrowDown") {
      setHighlighted((prev) => Math.min(prev + 1, filteredOptions.length - 1));
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      setHighlighted((prev) => Math.max(prev - 1, 0));
      e.preventDefault();
    } else if (e.key === "Enter" && highlighted >= 0) {
      onSelect(filteredOptions[highlighted]);
      setOpen(false);
      setHighlighted(-1);
      setSearch("");
      e.preventDefault();
    } else if (e.key === "Escape") {
      setOpen(false);
      setHighlighted(-1);
      setSearch("");
      e.preventDefault();
    }
  };

  return (
    <div className={styles.dropdownContainer} style={{ width }}>
      <div
        className={`${styles.dropdownInput} ${disabled ? styles.disabled : ''}`}
        tabIndex={disabled ? -1 : 0}
        role="button"
        aria-haspopup="listbox"
        aria-expanded={open && !disabled}
        onClick={() => !disabled && setOpen((prev) => !prev)}
        onKeyDown={(e) => !disabled && handleKeyDown(e)}
        style={{ cursor: disabled ? "not-allowed" : "pointer" }}
        ref={inputRef}
      >
        {selected || <span className={styles.dropdownPlaceholder}>{placeholder}</span>}
        <span className={styles.dropdownArrow} aria-hidden="true">&#9662;</span>
      </div>
      {open && (
        <div
          tabIndex={-1}
          role="listbox"
          ref={listRef}
          className={
            styles.dropdownList +
            " " +
            (direction === "up" ? styles.dropdownListUp : styles.dropdownListDown)
          }
          style={{ width, maxHeight: 170, overflowY: "auto" }}
          onMouseDown={e => e.preventDefault()}
        >
          <input
            type="text"
            className={styles.dropdownSearchInput}
            placeholder="Search..."
            value={search}
            onChange={e => {
              setSearch(e.target.value);
              setHighlighted(0);
            }}
            onKeyDown={handleKeyDown}
            autoFocus
            aria-label="Search options"
          />
          {filteredOptions.length === 0 && (
            <div className={styles.dropdownNoOption}>No options found</div>
          )}
          {filteredOptions.map((opt, idx) => (
            <div
              key={opt}
              role="option"
              aria-selected={selected === opt}
              onClick={() => {
                onSelect(opt);
                setOpen(false);
                setHighlighted(-1);
                setSearch("");
              }}
              onMouseEnter={() => setHighlighted(idx)}
              ref={el => optionRefs.current[idx] = el}
              className={
                `${styles.dropdownOption} ` +
                (highlighted === idx ? styles.highlighted : selected === opt ? styles.selected : "")
              }
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default NewCommonDropdown;
