/**
 * UserAssignmentUpdate - User Update page
 * Displays the Update User form
 */
import React from "react";
import UpdateUser from "./UpdateUser";
import styles from "./UserAssignmentUpdate.module.css";

const UserAssignmentUpdate = () => {
  return (
    <div className={styles.pageWrapper}>
      <div className={styles.splitContainer}>
        {/* Update User */}
        <div className={styles.box}>
          <UpdateUser embedded={true} />
        </div>
      </div>
    </div>
  );
};

export default UserAssignmentUpdate;
