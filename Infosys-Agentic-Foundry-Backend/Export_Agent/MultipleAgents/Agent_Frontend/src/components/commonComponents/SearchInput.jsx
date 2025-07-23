import React from "react";
import styles from "./SearchInput.module.css";
import SVGIcons from "../../Icons/SVGIcons";

const SearchInput = (props) => {
  const { inputProps, handleSearch } = props;

  const handleChange = (e) => {
    handleSearch(e.target.value);
  };

  return (
    <div className={styles.searchContainer}>
      <input
        type="text"
        className={styles.searchInput}
        {...inputProps}
        onChange={handleChange}
      />
      <button onClick={(e) => e.preventDefault()}>
        <SVGIcons icon="search" fill="#ffffff" width={12} height={12} />
      </button>
    </div>
  );
};

export default SearchInput;
