import React from "react";
import style from "../../css_modules/Loader.module.css";
import loaderGif from "../../Assets/loading.gif"

const Loader = () => {
  return (
    <div className={style["loader-backdrop"]}>
      {/* <div className={style["loader-spinner"]}></div> */}

      <img src={loaderGif} alt="Loading..." className="loader-gif" />
    </div>
  );
};

export default Loader;
