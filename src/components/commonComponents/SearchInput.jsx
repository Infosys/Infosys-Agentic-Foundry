import { useEffect, useState, useId } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SearchInputTools.module.css";

const SearchInput = ({ inputProps, handleSearch, searchValue, clearSearch }) => {
  // Fallback to no-op if clearSearch is not provided
  const safeClearSearch = typeof clearSearch === "function" ? clearSearch : () => {};
  const [localSearchValue, setLocalSearchValue] = useState(searchValue || "");

  const uniqueId = useId();

  useEffect(() => {
    setLocalSearchValue(searchValue);
  }, [searchValue]);

  const handleInputChange = (e) => {
    const value = e.target.value;
    setLocalSearchValue(value);
    if (value.trim() === "") {
      const toClearTheValueFully = setTimeout(() => {
        safeClearSearch();
        handleSearch("");
        clearTimeout(toClearTheValueFully);
      }, 500); // Show all items when search is cleared
    }
  };

  const handleSearchClick = () => {
    const trimmedValue = localSearchValue?.trim();

    if (trimmedValue) {
      handleSearch(trimmedValue);
    }
  };

  const handleClearSearch = () => {
    setLocalSearchValue("");
    safeClearSearch();
    handleSearch(""); // Show all items when search is cleared
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      handleSearchClick();
    }
  };

  return (
    <div className={styles.searchContainer}>
      <input
        type="text"
        value={localSearchValue}
        onChange={handleInputChange}
        onKeyDown={handleKeyDown}
        {...inputProps}
        className={styles.searchInput}
        placeholder={inputProps?.placeholder || "Search..."}
        id={uniqueId}
      />
      <button onClick={handleSearchClick} className={styles.searchButton} title="Search">
        <SVGIcons icon="search" width={16} height={16} fill="#fff" />
      </button>
      {localSearchValue && (
        <button onClick={handleClearSearch} className={styles.clearButton} title="Clear">
          <SVGIcons icon="close-icon" width={20} height={20} color="currentColor" />
        </button>
      )}
    </div>
  );
};

export default SearchInput;
