import React from "react";
import styles from "../css_modules/Layout.module.css";
import NavBar from "./NavBar";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import FloatingChatBot from "./FloatingChatBot";

const Layout = (props) => {
  const { children } = props;
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className={styles.mainContainer}>
      <div className={styles.container}>
        <NavBar />
        <div className={styles.dashboardContainer}>{children}</div>
      </div>
      {/* Floating ChatBot - visible on all pages except chat page */}
      <FloatingChatBot />
    </div>
  );
};

export default Layout;
