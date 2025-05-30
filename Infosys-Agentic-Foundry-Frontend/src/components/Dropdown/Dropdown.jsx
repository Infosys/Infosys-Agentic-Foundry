import React, { useEffect, useState } from "react";
import styles from "./Dropdown.module.css";
import SVGIcons from "../../Icons/SVGIcons";

const Dropdown = (props) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedOptions, setSelectedOptions] = useState([]);
  const [filteredOptions, setFilteredOptions] = useState([]);
  const [isDropdownVisible, setIsDropdownVisible] = useState(false);
  // const [dropdownPosition, setDropdownPosition] = useState(0);
  // const inputContainerRef = useRef(null);

  const handleSearchChange = (e) => {
    setSearchTerm(e.target.value);
    setIsDropdownVisible(true);
  };

  const handleSelectOption = (option) => {
    const isOptionSelected = selectedOptions.some(
      (opt) => opt.tag_id === option.tag_id
    );

    if (!isOptionSelected) {
      setSelectedOptions((prev) => [option, ...prev]);
    }
    props.setTags((prev) =>
      prev.map((tag) =>
        tag.tag_id === option.tag_id ? { ...tag, selected: true } : tag
      )
    );

    setSearchTerm("");
    setIsDropdownVisible(false);
  };

  const handleRemoveOption = (option) => {
    setSelectedOptions((prev) =>
      prev.filter((selected) => selected.tag_id !== option.tag_id)
    );
    props.setTags((prev) =>
      prev.map((tag) =>
        tag.tag_id === option.tag_id ? { ...tag, selected: false } : tag
      )
    );
  };

  useEffect(() => {
    setFilteredOptions(
      props.tags.filter(
        (option) =>
          option.tag_name?.toLowerCase().includes(searchTerm?.toLowerCase()) &&
          !selectedOptions.includes(option) &&
          !option.selected
      )
    );
    setSelectedOptions(props.tags.filter((option) => option.selected));
  }, [props.tags]);

  useEffect(() => {
    console.log("Changed");
    console.log(
      "Change Selected Options",
      props.tags.filter((option) => option.selected)
    );
    console.log("selected Options", selectedOptions);
    console.log(
      "Change Filtered Options",
      props.tags.filter(
        (option) =>
          option.tag_name?.toLowerCase().includes(searchTerm?.toLowerCase()) &&
          !selectedOptions.some((opt) => opt.tag_id === option.tag_id) &&
          !option?.selected
      )
    );
    setFilteredOptions(
      props.tags.filter(
        (option) =>
          option.tag_name?.toLowerCase()?.includes(searchTerm?.toLowerCase()) &&
          !selectedOptions.some((opt) => opt?.tag_id === option?.tag_id) &&
          !option?.selected
      )
    );
  }, [selectedOptions, searchTerm]);
  console.log("Selected Options", selectedOptions);
  console.log("Filtered Options", filteredOptions);
  useEffect(() => {
    props.setSelectedTags(selectedOptions);
  }, [selectedOptions]);

  return (
    <div className={props.styles.dropdownContainer}>
      <div className={styles.inputWithTags}>
        <div
          className={styles.iconContainer}
          onClick={() => setIsDropdownVisible(!isDropdownVisible)}
        >
          {isDropdownVisible ? (
            <SVGIcons fill="white" icon="drop_arrow_up" />
          ) : (
            <SVGIcons fill="white" icon="drop_arrow_down" />
          )}
        </div>
        <input
          type="text"
          className={styles.searchInput}
          placeholder={"Search/Select Tags"}
          value={searchTerm}
          onChange={handleSearchChange}
          onFocus={() => setIsDropdownVisible(true)}
        />
        <div className={styles.selectedTags}>
          {selectedOptions.map((option) => (
            <span key={option.tag_id} className={styles.tag}>
              {option.tag_name}
              <span
                className={styles.closeBtn}
                onClick={() => handleRemoveOption(option)}
              >
                X
              </span>
            </span>
          ))}
        </div>

        {isDropdownVisible && filteredOptions?.length > 0 && (
          <ul className={styles.dropdownList}>
            {filteredOptions.map((option) => (
              <li
                key={option.tag_id}
                onClick={() => handleSelectOption(option)}
              >
                {option.tag_name}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

export default Dropdown;
