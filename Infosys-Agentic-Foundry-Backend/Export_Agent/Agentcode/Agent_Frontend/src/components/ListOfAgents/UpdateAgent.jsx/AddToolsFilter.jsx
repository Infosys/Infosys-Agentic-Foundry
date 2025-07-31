import React, { useEffect, useState } from "react";
import styles from "../../commonComponents/FilterModal.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

const AddToolsFilterModal = ({ show, onClose, tags, handleFilter, selectedTags }) => {
  const [localSelectedTags, setLocalSelectedTags] = useState([]);
  const [tempSelectedTags, setTempSelectedTags] = useState([]);

  useEffect(() => {
    setLocalSelectedTags(selectedTags);
    setTempSelectedTags(selectedTags);
  }, [selectedTags]);

  const handleTagChange = (tagId) => {
    setTempSelectedTags((prevTags) =>
      prevTags.includes(tagId)
        ? prevTags.filter((t) => t !== tagId)
        : [...prevTags, tagId]
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
    setTempSelectedTags(localSelectedTags);
    onClose();
  };

  const hasChanges = () => {
    if (tempSelectedTags.length !== localSelectedTags.length) return true;
    return !tempSelectedTags.every((tag) => localSelectedTags.includes(tag));
  };

  if (!show) return null;

  return (
    <div className={styles.modal}>
      <div className={styles.modalContent}>
        <h2 className={styles.heading}>Update Tags</h2>
        <div className={styles.tagsContainer}>
          {tags.map((tag) => (
            <div
              key={tag.tag_id}
              className={`${styles.tag} ${
                tempSelectedTags.includes(tag.tag_id) ? styles.selectedTag : ""
              }`}
            >
              <input
                type="checkbox"
                id={tag.tag_id}
                value={tag.tag_name}
                checked={tempSelectedTags.includes(tag.tag_id)}
                onChange={() => handleTagChange(tag.tag_id)}
              />
              <label htmlFor={tag.tag_id}>{tag.tag_name}</label>
            </div>
          ))}
        </div>
        <button 
            onClick={applyFilter} 
            className={styles.applyButton}
            disabled={!hasChanges()}
        >
          Update
        </button>
        <button onClick={clearFilter} className={styles.clearButton}>
          Clear All
        </button>
        <button onClick={handleClose} className={styles.closeButton}>
          <SVGIcons icon="fa-xmark" fill="#3D4359" />
        </button>
      </div>
    </div>
  );
};

export default AddToolsFilterModal;