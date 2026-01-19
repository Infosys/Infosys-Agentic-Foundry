import style from "../../css_modules/Loader.module.css";
import loaderGif from "../../Assets/loading.gif";

const Loader = ({ contained = false }) => {
  return (
    <div className={`${style["loader-backdrop"]} ${contained ? style["loader-contained"] : ""}`}>
      <img src={loaderGif} alt="Loading..." className="loader-gif" />
    </div>
  );
};

export default Loader;
