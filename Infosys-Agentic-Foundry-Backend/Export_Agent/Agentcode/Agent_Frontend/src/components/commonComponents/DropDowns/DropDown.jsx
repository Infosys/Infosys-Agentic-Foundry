import React from "react";
import styles from "./DropDown.module.css";

const DropDown = (props) => {
  const {
    options,
    selectStyle,
    containerStyle,
    placeholder,
    isSearch,
    ...rest
  } = props;
  const containerClass = containerStyle
    ? `${containerStyle} ${styles.dropdownContainer}`
    : styles.dropdownContainer;
  const selectClass = selectStyle
    ? `${selectStyle} ${styles.selectContainer}`
    : styles.selectContainer;

  return (
    <div className={containerClass}>
      <select className={selectClass} {...rest}>
        {placeholder && (
          <option hidden value="">
            {placeholder}
          </option>
        )}
        {options.map((option,index) => (
         // <option value={option?.value || option}>
           <option key={option.id || `option-${index}`} value={option.value}>

            {option?.label || option}
          </option>
        ))}
      </select>
    </div>
  );
};

export default DropDown;
