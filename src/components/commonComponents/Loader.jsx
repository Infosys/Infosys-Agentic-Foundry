import React from "react";
import style from "../../css_modules/Loader.module.css";

const Loader = () => {
  return (
    <div className={style["loader-backdrop"]}>
      <img src="/images/loading.gif" alt="Loading..." />
    </div>
  );
};

export default Loader;
