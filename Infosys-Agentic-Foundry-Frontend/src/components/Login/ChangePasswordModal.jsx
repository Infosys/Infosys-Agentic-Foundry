import React, { useState } from "react";
import { createPortal } from "react-dom";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import useFetch from "../../Hooks/useAxios";
import { APIs } from "../../constant";
import styles from "./ChangePasswordModal.module.css";

const ChangePasswordModal = ({ onSuccess, onClose, userEmail }) => {
  const { postData } = useFetch();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [touched, setTouched] = useState({
    currentPassword: false,
    newPassword: false,
    confirmPassword: false,
  });

  const passwordRegex = /^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+[\]{};':"\\|,.<>/?]).{8,}$/;

  const validateNewPassword = (password) => {
    if (!password) return "New password is required";
    if (!passwordRegex.test(password)) {
      return "Must be at least 8 characters, include one uppercase, one number, and one special character";
    }
    return "";
  };

  const validateConfirmPassword = (password) => {
    if (!password) return "Please confirm your password";
    if (password !== newPassword) return "Passwords do not match";
    return "";
  };

  const isFormValid = 
    currentPassword.trim() !== "" &&
    newPassword.trim() !== "" &&
    confirmPassword.trim() !== "" &&
    !validateNewPassword(newPassword) &&
    !validateConfirmPassword(confirmPassword);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setTouched({
      currentPassword: true,
      newPassword: true,
      confirmPassword: true,
    });

    if (!isFormValid) {
      setError("Please fix the errors before submitting");
      return;
    }

    setIsLoading(true);
    setError("");
    setSuccess("");

    try {
      const response = await postData(APIs.CHANGE_PASSWORD, {
        current_password: currentPassword,
        new_password: newPassword,
      });

      setSuccess(response?.message || response?.detail || "Password changed successfully! Redirecting to login...");
      
      setTimeout(() => {
        onSuccess();
      }, 2000);
    } catch (err) {
      const apiError = err?.response?.data?.detail || 
                       err?.response?.data?.message || 
                       err?.message || 
                       "Failed to change password. Please try again.";
      setError(apiError);
    } finally {
      setIsLoading(false);
    }
  };

  const handleBlur = (field) => {
    setTouched((prev) => ({ ...prev, [field]: true }));
  };

  const modalContent = (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <SVGIcons icon="lock" width={24} height={24} stroke="var(--accent)" />
          <h2 className={styles.title}>Password Reset Required</h2>
        </div>
        
        <p className={styles.description}>
          Your administrator has reset your password. Please set a new password to continue.
        </p>

        {userEmail && (
          <div className={styles.userInfo}>
            <SVGIcons icon="mail" width={16} height={16} stroke="var(--muted)" />
            <span>{userEmail}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.inputGroup}>
            <label className={styles.label}>Current Password (Temporary)</label>
            <div className={styles.inputWrapper}>
              <input
                type={showCurrentPassword ? "text" : "password"}
                className={styles.input}
                value={currentPassword}
                onChange={(e) => { setCurrentPassword(e.target.value); if (!touched.currentPassword) setTouched((prev) => ({ ...prev, currentPassword: true })); }}
                onBlur={() => handleBlur("currentPassword")}
                placeholder="Enter temporary password from admin"
                autoComplete="current-password"
              />
              <button
                type="button"
                className={styles.eyeButton}
                onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                aria-label={showCurrentPassword ? "Hide password" : "Show password"}
              >
                <SVGIcons 
                  icon={showCurrentPassword ? "eye-off" : "eye"} 
                  width={18} 
                  height={18} 
                  stroke="var(--muted)" 
                />
              </button>
            </div>
            {touched.currentPassword && !currentPassword && (
              <span className={styles.errorText}>Current password is required</span>
            )}
          </div>

          <div className={styles.inputGroup}>
            <label className={styles.label}>New Password</label>
            <div className={styles.inputWrapper}>
              <input
                type={showNewPassword ? "text" : "password"}
                className={styles.input}
                value={newPassword}
                onChange={(e) => { setNewPassword(e.target.value); if (!touched.newPassword) setTouched((prev) => ({ ...prev, newPassword: true })); }}
                onBlur={() => handleBlur("newPassword")}
                placeholder="Enter new password"
                autoComplete="new-password"
              />
              <button
                type="button"
                className={styles.eyeButton}
                onClick={() => setShowNewPassword(!showNewPassword)}
                aria-label={showNewPassword ? "Hide password" : "Show password"}
              >
                <SVGIcons 
                  icon={showNewPassword ? "eye-off" : "eye"} 
                  width={18} 
                  height={18} 
                  stroke="var(--muted)" 
                />
              </button>
            </div>
            {touched.newPassword && validateNewPassword(newPassword) && (
              <span className={styles.errorText}>{validateNewPassword(newPassword)}</span>
            )}
          </div>

          <div className={styles.inputGroup}>
            <label className={styles.label}>Confirm New Password</label>
            <div className={styles.inputWrapper}>
              <input
                type={showConfirmPassword ? "text" : "password"}
                className={styles.input}
                value={confirmPassword}
                onChange={(e) => { setConfirmPassword(e.target.value); if (!touched.confirmPassword) setTouched((prev) => ({ ...prev, confirmPassword: true })); }}
                onBlur={() => handleBlur("confirmPassword")}
                placeholder="Confirm new password"
                autoComplete="new-password"
              />
              <button
                type="button"
                className={styles.eyeButton}
                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                aria-label={showConfirmPassword ? "Hide password" : "Show password"}
              >
                <SVGIcons 
                  icon={showConfirmPassword ? "eye-off" : "eye"} 
                  width={18} 
                  height={18} 
                  stroke="var(--muted)" 
                />
              </button>
            </div>
            {touched.confirmPassword && validateConfirmPassword(confirmPassword) && (
              <span className={styles.errorText}>{validateConfirmPassword(confirmPassword)}</span>
            )}
          </div>

          {error && <div className={styles.errorBox}>{error}</div>}
          {success && <div className={styles.successBox}>{success}</div>}

          <div className={styles.requirements}>
            <p className={styles.requirementsTitle}>Password must contain:</p>
            <ul className={styles.requirementsList}>
              <li className={newPassword.length >= 8 ? styles.valid : ""}>At least 8 characters</li>
              <li className={/[A-Z]/.test(newPassword) ? styles.valid : ""}>One uppercase letter</li>
              <li className={/\d/.test(newPassword) ? styles.valid : ""}>One number</li>
              <li className={/[!@#$%^&*()_+[\]{};':"\\|,.<>/?]/.test(newPassword) ? styles.valid : ""}>One special character</li>
            </ul>
          </div>

          <div className={styles.footer}>
            <IAFButton
              type="primary"
              htmlType="submit"
              disabled={!isFormValid || isLoading}
              loading={isLoading}
              style={{ width: "100%", flexDirection: "row-reverse" }}
              icon={!isLoading && <SVGIcons icon="arrow-right" width={12} height={10} stroke="currentColor" />}
            >
              {isLoading ? "Changing Password..." : "Change Password"}
            </IAFButton>
          </div>
        </form>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
};

export default ChangePasswordModal;
