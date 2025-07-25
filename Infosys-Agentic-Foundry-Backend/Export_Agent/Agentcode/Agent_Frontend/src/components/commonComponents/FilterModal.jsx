import React, { useEffect, useState } from "react";
import styles from "./FilterModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";

const FilterModal = ({ show, onClose, tags, handleFilter, selectedTags }) => {
  const [localSelectedTags, setLocalSelectedTags] = useState([]);
  const [tempSelectedTags, setTempSelectedTags] = useState([]);

  useEffect(() => {
    setLocalSelectedTags(selectedTags);
    setTempSelectedTags(selectedTags); // Initialize temp state with prop
  }, [selectedTags]);

  const handleTagChange = (tagName) => {
    setTempSelectedTags((prevTags) =>
      prevTags.includes(tagName)
        ? prevTags.filter((t) => t !== tagName)
        : [...prevTags, tagName]
    );
  };

  const applyFilter = () => {
    handleFilter(tempSelectedTags);
    onClose();
  };

  const clearFilter = () => {
    setTempSelectedTags([]);
    handleFilter([]);
  };

  const handleClose = () => {
    setTempSelectedTags(localSelectedTags); // Revert temp state on close
    onClose();
  };

  if (!show) return null;

  return (
    <div className={styles.modal}>
      <div className={styles.modalContent}>
        <h2 className={styles.heading}>Filter Tools by Tags</h2>
        <div className={styles.tagsContainer}>
          {tags.map((tag) => (
            <div
              key={tag.tag_id}
              className={`${styles.tag} ${
                tempSelectedTags.includes(tag.tag_name) ? styles.selectedTag : ""
              }`}
            >
              <input
                type="checkbox"
                id={tag.tag_id}
                value={tag.tag_name}
                checked={tempSelectedTags.includes(tag.tag_name)}
                onChange={() => handleTagChange(tag.tag_name)}
              />
              <label htmlFor={tag.tag_id}>{tag.tag_name}</label>
            </div>
          ))}
        </div>
        <button onClick={applyFilter} className={styles.applyButton}>
          Apply Filter
        </button>
        <button onClick={clearFilter} className={styles.clearButton}>
          Clear Filter
        </button>
        <button onClick={handleClose} className={styles.closeButton}>
          <SVGIcons icon="fa-xmark" fill="#3D4359" />
        </button>
      </div>
    </div>
  );
};

export default FilterModal;