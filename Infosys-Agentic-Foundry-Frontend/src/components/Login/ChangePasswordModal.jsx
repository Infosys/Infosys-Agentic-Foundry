import React, { useState } from "react";
import { createPortal } from "react-dom";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import useFetch from "../../Hooks/useAxios";
import { APIs } from "../../constant";
import styles from "./ChangePasswordModal.module.css";
import { encodePassword } from "../../utils/encodeUtils";

const ChangePasswordModal = ({ onSuccess, onClose, userEmail }) => {
  const { postData } = useFetch();

  const [currentPwd, setCurrentPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [touched, setTouched] = useState({
    currentPwd: false,
    newPwd: false,
    confirmPwd: false,
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
    if (password !== newPwd) return "Passwords do not match";
    return "";
  };

  const isFormValid =
    currentPwd.trim() !== "" &&
    newPwd.trim() !== "" &&
    confirmPwd.trim() !== "" &&
    !validateNewPassword(newPwd) &&
    !validateConfirmPassword(confirmPwd);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setTouched({
      currentPwd: true,
      newPwd: true,
      confirmPwd: true,
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
        current_password: encodePassword(currentPwd),
        new_password: encodePassword(newPwd),
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
                value={currentPwd}
                onChange={(e) => { setCurrentPwd(e.target.value); if (!touched.currentPwd) setTouched((prev) => ({ ...prev, currentPwd: true })); }}
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
            {touched.currentPwd && !currentPwd && (
              <span className={styles.errorText}>Current password is required</span>
            )}
          </div>

          <div className={styles.inputGroup}>
            <label className={styles.label}>New Password</label>
            <div className={styles.inputWrapper}>
              <input
                type={showNewPassword ? "text" : "password"}
                className={styles.input}
                value={newPwd}
                onChange={(e) => { setNewPwd(e.target.value); if (!touched.newPwd) setTouched((prev) => ({ ...prev, newPwd: true })); }}
                onBlur={() => handleBlur("newPwd")}
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
            {touched.newPwd && validateNewPassword(newPwd) && (
              <span className={styles.errorText}>{validateNewPassword(newPwd)}</span>
            )}
          </div>

          <div className={styles.inputGroup}>
            <label className={styles.label}>Confirm New Password</label>
            <div className={styles.inputWrapper}>
              <input
                type={showConfirmPassword ? "text" : "password"}
                className={styles.input}
                value={confirmPwd}
                onChange={(e) => { setConfirmPwd(e.target.value); if (!touched.confirmPwd) setTouched((prev) => ({ ...prev, confirmPwd: true })); }}
                onBlur={() => handleBlur("confirmPwd")}
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
            {touched.confirmPwd && validateConfirmPassword(confirmPwd) && (
              <span className={styles.errorText}>{validateConfirmPassword(confirmPwd)}</span>
            )}
          </div>

          {error && <div className={styles.errorBox}>{error}</div>}
          {success && <div className={styles.successBox}>{success}</div>}

          <div className={styles.requirements}>
            <p className={styles.requirementsTitle}>Password must contain:</p>
            <ul className={styles.requirementsList}>
              <li className={newPwd.length >= 8 ? styles.valid : ""}>At least 8 characters</li>
              <li className={/[A-Z]/.test(newPwd) ? styles.valid : ""}>One uppercase letter</li>
              <li className={/\d/.test(newPwd) ? styles.valid : ""}>One number</li>
              <li className={/[!@#$%^&*()_+[\]{};':"\\|,.<>/?]/.test(newPwd) ? styles.valid : ""}>One special character</li>
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
