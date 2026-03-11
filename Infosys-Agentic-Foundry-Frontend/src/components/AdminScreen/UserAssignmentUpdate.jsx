/**
 * UserAssignmentUpdate - Combined page for User Assignment and Update
 * Displays both forms in separate animated boxes with a vertical divider
 */
import React from "react";
import SignUp from "../Register/SignUp";
import UpdateUser from "./UpdateUser";
import styles from "./UserAssignmentUpdate.module.css";

const UserAssignmentUpdate = () => {
  return (
    <div className={styles.pageWrapper}>
      <div className={styles.splitContainer}>
        {/* Left Box - Assignment */}
        <div className={styles.box}>
          <SignUp isAdminScreen={true} embedded={true} />
        </div>

        {/* Vertical Divider */}
        <div className={styles.divider}>
          <div className={styles.dividerLine}></div>
        </div>

        {/* Right Box - Update */}
        <div className={styles.box}>
          <UpdateUser embedded={true} />
        </div>
      </div>
    </div>
  );
};

export default UserAssignmentUpdate;
