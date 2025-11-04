import React, { useEffect, useState } from "react";
import styles from "../../commonComponents/FilterModal.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import Tag from "../../Tag/Tag";

const AddToolsFilterModal = ({ show, onClose, tags, handleFilter, selectedTags }) => {
  const [localSelectedTags, setLocalSelectedTags] = useState([]);
  const [tempSelectedTags, setTempSelectedTags] = useState([]);

  useEffect(() => {
    setLocalSelectedTags(selectedTags);
    setTempSelectedTags(selectedTags);
  }, [selectedTags]);

  const handleTagChange = (index) => {
    const tagId = tags[index].tag_id;
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
        <h2 className={styles.heading}>Update Tags For Agent</h2>
        <div className={styles.tagsContainer}>
          {tags.map((tag, idx) => (
            <Tag
              key={tag.tag_id}
              tag={tag.tag_name}
              selected={tempSelectedTags.includes(tag.tag_id)}
              toggleTagSelection={() => handleTagChange(idx)}
              index={idx}
            />
          ))}
        </div>
        <button 
            onClick={applyFilter} 
            className={styles.applyButton}
            disabled={!hasChanges()}
        >
          Modify
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