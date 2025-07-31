import React from "react";
import styles from "../css_modules/Layout.module.css";
import NavBar from "./NavBar";
import Header from "./Header";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const Layout = (props) => {
  const { children } = props;
  const { pathname } = useLocation();
  
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  
  return (
    <div className={styles.mainContainer}>
      <div className={styles.header}>
        <Header />
      </div>
      <div className={styles.container}>
        {/* <NavBar /> */}
        <div className={styles.dashboardContainer}>{children}</div>
      </div>
    </div>
  );
};

export default Layout;
