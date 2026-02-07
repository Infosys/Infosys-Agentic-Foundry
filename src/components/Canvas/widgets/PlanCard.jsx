import React, { useState } from "react";
import styles from "../widgets/PlanCard.module.css";
import Toggle from "../../commonComponents/Toggle";
import planDefaultMap from "../../../Assets/plan-default-map.png";

const PlanCard = ({ content ,sendUserMessage}) => {
  const [toggle, setToggle] = useState(true);
  if (!content) return null;
  const {
    title,
    description,
    image,
    location,
    local_benifit,
    roming_benefit,
    toogle_name,
    toogle_description,
    benefits_with_toogle,
    benefits_without_toogle,
    price_with_toogle,
    price_without_toogle,
    button_name
  } = content;

  const benefits = toggle ? benefits_with_toogle : benefits_without_toogle;

  return (
    <div className={styles.card} aria-label={title}>
      <div className={styles.titleRow}>
        <h2 className={styles.title}>{title}</h2>
      </div>
      <div className={styles.descriptionRow}>
        <p className={styles.description}>{description}</p>
      </div>
      <img src={planDefaultMap} alt="Plan Map" className={styles.cardImage} />
      <div className={styles.featureRow}>
        <span className={styles.icon} aria-label="Location">📍</span>
        <span>{location}</span>
      </div>
      <div className={styles.featureRow}>
        <span className={styles.icon} aria-label="Local Benefit">🌐</span>
        <span className={styles.benifitsContent}>{local_benifit}</span>
      </div>
      <div className={styles.featureRow}>
        <span className={styles.icon} aria-label="Roaming Benefit">🛫</span>
        <span className={styles.benifitsContent}>{roming_benefit}</span>
      </div>
      <div className={styles.toggleRow}>
        <span className={styles.toggleLabel}>{toogle_name}</span>
        <Toggle value={toggle} onChange={() => setToggle((t) => !t)} />
      </div>
      {toogle_description && <div className={styles.tvDetailsBelow}>{toogle_description}</div>}
      <div className={styles.benefitsBox}>
        <div className={styles.benefitsTitle}>Benefits</div>
        <ul className={styles.benefitsList}>
          {(Array.isArray(benefits) ? benefits : []).map((b, i) => (
            <li key={i} className={styles.benefitItem}>
              <span className={styles.check}>
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg" style={{ verticalAlign: 'middle' }}>
                  <path d="M5 9.5L8 12.5L13 7.5" stroke="#cc0011" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              </span> <span className={styles.benifitsContent}>{b}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className={styles.priceRow}>
        {toggle ? (
          <span className={styles.price}>{price_with_toogle}</span>
        ) : (
          <span className={styles.price}>{price_without_toogle}</span>
        )}
      </div>
  <button
    className={styles.mainButton}
    onClick={() => {
      const query = `Buy ${title} ${toggle ? "with" : "without"} ${toogle_name}`;
      const payload = { query, context_flag: true, response_formatting_flag: false };
      sendUserMessage(payload);
    }}
  >
    {button_name}
  </button>
    </div>
  );
};

export default PlanCard;
