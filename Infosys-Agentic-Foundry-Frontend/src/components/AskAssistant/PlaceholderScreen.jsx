import SVGIcons from "../../Icons/SVGIcons";
import styles from "./PlaceholderScreen.module.css";

const PlaceholderScreen = () => {
  return (
    <div className={styles.container}>
      <div className={styles.content}>
        {/* Title */}
        <h1 className={styles.title}>Welcome to Infosys Agentic Foundry</h1>

        {/* Subtitle */}
        <p className={styles.subtitle}>Your intelligent AI agent management platform. Configure your preferences and start collaborating with advanced AI agents.</p>

        {/* Feature Cards */}
        <div className={styles.featuresContainer}>
          <div className={styles.feature}>
            <div className={`${styles.featureIconWrapper} ${styles.featureIconPrimary}`}>
              <SVGIcons icon="brain" width={24} height={24} />
            </div>
            <p className={styles.featureText}>Intelligent Agents</p>
          </div>
          <div className={styles.feature}>
            <div className={`${styles.featureIconWrapper} ${styles.featureIconPrimary}`}>
              <SVGIcons icon="bolt" width={24} height={24} />
            </div>
            <p className={styles.featureText}>Powered Responses</p>
          </div>
          <div className={styles.feature}>
            <div className={`${styles.featureIconWrapper} ${styles.featureIconPrimary}`}>
              <SVGIcons icon="circle-check" width={24} height={24} />
            </div>
            <p className={styles.featureText}>Reliable Results</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PlaceholderScreen;
