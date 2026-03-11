import React from "react";
import styles from "./VerticalNavigation.module.css";

const VerticalNavigation = ({ navItems, activeIndex = 1 }) => {
  return (
    <nav className={styles.sidebar} aria-label="Sidebar Navigation">
      <ul className={styles.navList}>
        {navItems.map((item, idx) => {
          let itemClass = styles.navItem;
          if (item.state === "active" && idx === activeIndex) itemClass += ` ${styles.active}`;
          else if (item.state === "default" && idx === 0) itemClass += ` ${styles.default}`;
          else if (item.state === "hover" && idx === 2) itemClass += ` ${styles.hover}`;
          return (
            <li key={item.label}>
              <button type="button" className={itemClass} tabIndex={0} aria-current={item.state === "active" && idx === activeIndex ? "page" : undefined}>
                {item.icon}
                <span className={styles.label}>{item.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};

export default VerticalNavigation;
