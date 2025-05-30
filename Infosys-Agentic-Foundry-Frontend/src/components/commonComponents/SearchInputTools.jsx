import React, { useEffect, useState } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SearchInputTools.module.css";

const SearchInput = ({ inputProps, handleSearch, searchValue, clearSearch }) => {
  const [localSearchValue, setLocalSearchValue] = useState(searchValue || "");

  useEffect(() => {
    setLocalSearchValue(searchValue);
  }, [searchValue]);

  const handleInputChange = (e) => {
    const value = e.target.value;
    setLocalSearchValue(value);

    if(value.trim() === ""){
      clearSearch();
    }
  };

  const handleSearchClick = () => {
    const trimmedValue = localSearchValue.trim();
    if (trimmedValue) {
      handleSearch(trimmedValue);
    }
  };

  const handleClearSearch = () => {
    setLocalSearchValue("");
    clearSearch();
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
        placeholder="Search..."
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