import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Blue-2.png";
import { faRobot, faBrain, faUsers, faGear, faComments, faStar } from "@fortawesome/free-solid-svg-icons";
import styles from "./PlaceholderScreen.module.css";

const PlaceholderScreen = ({ agentType, model, selectedAgent }) => {
  const getPlaceholderContent = () => {
    const missingFields = [];
    if (!agentType) missingFields.push("Agent Type");
    if (!model) missingFields.push("Model");
    if (!selectedAgent) missingFields.push("Agent");

    if (missingFields.length === 3) {
      return {
        icon: faComments,
        title: "Welcome to Agentic Chat",
        subtitle: "Get started by selecting your preferences",
        description: "Choose your agent type, model, and specific agent to begin an intelligent conversation.",
        steps: ["Select an Agent Type (Meta, Multi, ReAct, or Custom)", "Choose your preferred AI Model", "Pick a specific Agent for your task"],
      };
    }

    if (missingFields.length === 2) {
      return {
        icon: faGear,
        title: "Almost Ready!",
        subtitle: `Please select ${missingFields.join(" and ")}`,
        description: "Just a couple more selections and we'll be ready to chat.",
        steps: missingFields.map((field) => `Select ${field}`),
      };
    }

    if (missingFields.length === 1) {
      return {
        icon: faStar,
        title: "One More Step!",
        subtitle: `Please select ${missingFields[0]}`,
        description: "You're almost there! One more selection and we can start our conversation.",
        steps: [`Choose your ${missingFields[0]}`],
      };
    }

    return {
      icon: faRobot,
      title: "Ready to Chat!",
      subtitle: "All set! Your AI assistant is ready.",
      description: "You can now start chatting with your selected AI agent.",
      steps: [],
    };
  };

  const content = getPlaceholderContent();

  return (
    <div className={styles.container}>
      <div className={styles.content}>
        {/* Animated Icon */}
        <div className={styles.iconContainer}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", position: "relative", flexDirection: "column" }}>
            <img style={{ marginBottom: "20px", width: "100%", maxWidth: "350px" }} src={brandlogotwo} alt="Brandlogo" />
            <FontAwesomeIcon icon={content.icon} className={styles.mainIcon} />
          </div>
          <div className={styles.iconGlow}></div>
        </div>

        {/* Title and Subtitle */}
        <div className={styles.textContainer}>
          <h1 className={styles.title}>{content.title}</h1>
          <p className={styles.subtitle}>{content.subtitle}</p>
          <p className={styles.description}>{content.description}</p>
        </div>

        {/* Steps */}
        {/* {content.steps.length > 0 && (
          <div className={styles.stepsContainer}>
            <h3 className={styles.stepsTitle}>Next Steps:</h3>
            <ul className={styles.stepsList}>
              {content.steps.map((step, index) => (
                <li key={index} className={styles.stepItem}>
                  <span className={styles.stepNumber}>{index + 1}</span>
                  <span className={styles.stepText}>{step}</span>
                </li>
              ))}
            </ul>
          </div>
        )} */}

        {/* Feature Highlights */}
        <div className={styles.featuresContainer}>
          <div className={styles.feature}>
            <FontAwesomeIcon icon={faBrain} className={styles.featureIcon} />
            <span className={styles.featureText}>Intelligent Responses</span>
          </div>
          <div className={styles.feature}>
            <FontAwesomeIcon icon={faUsers} className={styles.featureIcon} />
            <span className={styles.featureText}>Multi-Agent Support</span>
          </div>
          <div className={styles.feature}>
            <FontAwesomeIcon icon={faGear} className={styles.featureIcon} />
            <span className={styles.featureText}>Customizable Tools</span>
          </div>
        </div>

        {/* Floating Elements for Animation */}
        <div className={styles.floatingElements}>
          <div className={styles.floatingElement} style={{ animationDelay: "0s" }}></div>
          <div className={styles.floatingElement} style={{ animationDelay: "2s" }}></div>
          <div className={styles.floatingElement} style={{ animationDelay: "4s" }}></div>
        </div>
      </div>
    </div>
  );
};

export default PlaceholderScreen;
