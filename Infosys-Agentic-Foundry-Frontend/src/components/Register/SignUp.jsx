import React, { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import SVGIcons from "../../Icons/SVGIcons";
import "./SignUp.css";
import useFetch from "../../Hooks/useAxios";
import { roleOptions } from "../../constant";

const SignUp = () => {
  const { postData, setCsrfToken } = useFetch();

  const [email, setEmail] = useState("");
  const [errEmail, setErrEmail] = useState("");
  const [username, setUsername] = useState("");
  const [errUser, setErrUser] = useState("");
  
  // Use a ref instead to avoid storing in state
  const passwordRef = useRef("");
  const confirmPasswordRef = useRef("");
  // Add this state variable with your other state declarations
  const [hasPasswordInput, setHasPasswordInput] = useState(false);
  const [hasConfirmPasswordInput, setHasConfirmPasswordInput] = useState(false);

  const [errPass, setErrPass] = useState("");
  const [errConfirmPass, setErrConfirmPass] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [items, setItems] = useState("");
  const [errSubmit, setErrSubmit] = useState(false);
  const [msgSubmit, setMsgSubmit] = useState("");
  const [msgSubmitApproval, setMsgSubmitApproval] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState("Select Role");

  const navigate = useNavigate();

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };
  const toggleConfirmPasswordVisibility = () => {
    setShowConfirmPassword((prev) => !prev);
  };

  const toggleDropdown = () => {
    setIsOpen(!isOpen);
  };

  const handleOptionSelect = (option) => {
    setSelectedOption(option);
    setIsOpen(false);
  };

  const emailChange = (value) => {
    const emailRegex = /^[a-zA-Z0-9+_.-]+@[a-zA-Z0-9.-]+\.(co|com)$/;
    setEmail(value);
    if (value) {
      if (!emailRegex.test(value)) {
        setErrEmail("Please enter a valid email address");
      } else {
        setErrEmail("");
      }
    } else {
      setErrEmail("");
    }
  }

  const usernameChange = (value) => {
    setUsername(value);
    if (value) {
      if (value?.length < 3) {
        setErrUser("Username must be atleast 3 characters long");
      } else {
        setErrUser("");
      }
    } else {
      setErrUser("");
    }
  };

  const passwordChange = (value) => {
    const passwordRegex =
      /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[!@#$%^&*()_+~`|}{[\]:;?><,./])/;
    // setPassword(value);
    // Commented above line and modified to below to over come vulnerability issue 
    // Store the password in the ref instead of state to overcome vulnerability
    passwordRef.current = value;

    // Update state to track if password field has content
    setHasPasswordInput(value.length > 0);

    if (value) {
      if (!passwordRegex.test(value)) {
        setErrPass(
          "Password must contain atleast one letter, one number and one special character"
        );
      } else {
        setErrPass("");
      }
    } else {
      setErrPass("");
    }
  };

  const confirmPasswordChange = (value) => {
    // setConfirmPassword(value);
    // Commented above line and modified to below to over come vulnerability issue 
    // Store the password in the ref instead of state to overcome vulnerability
    confirmPasswordRef.current = value;

    // Update state to track if password field has content
    setHasConfirmPasswordInput(value.length > 0);
     
    if (value !== passwordRef.current) {
      setErrConfirmPass("Passwords do not match");
    } else {
      setErrConfirmPass("");
    }
  };

  const onSubmit = async (e) => {
    e.preventDefault();

    if (email && username && passwordRef.current && selectedOption !== "Select Role") {
      if (passwordRef.current !== confirmPasswordRef.current) {
        setErrConfirmPass("Passwords do not match");
        return;
      }
      if(errEmail || errUser || errPass || errConfirmPass) {
        return;
      }

      try {

        const user = await postData("/registration", {
          email_id: email,
          password: passwordRef.current,
          role: selectedOption,
          user_name: username,
        });

        // Store CSRF token from response if it exists
        if (user?.csrf_token) {
          setCsrfToken(user.csrf_token);
        }

        if (user.approval) {
          setMsgSubmit(user.message);
          setMsgSubmitApproval(user.approval);
          setTimeout(() => {
            navigate("/login");
          }, 3000);
        } else {
          setMsgSubmit(user.message);
          setMsgSubmitApproval(user.approval);
          clearError();
        }
        // Clear the password from memory after use
        passwordRef.current = "";
        confirmPasswordRef.current = "";
      } catch (error) {
        setMsgSubmit("Something went wrong");
        setMsgSubmitApproval(false);
        clearError();
      } 
    } else {
      setMsgSubmit("Please fill all the fields");
      setMsgSubmitApproval(false);
      clearError();
    }
  };

  const clearError = () => {
    setTimeout(() => {
      setMsgSubmit("");
      setMsgSubmitApproval(false);
    }, 3000);
  };

  return (
    <div className="login-container">
      <h3 className="title">Register</h3>

      {/* Email */}
      <div className="flexrow">
        <input
          type="text"
          name="Email"
          className="login-input"
          placeholder="Email"
          value={email}
          onChange={(e) => emailChange(e.target.value)}
        />
        {errEmail && <span className="error-style">{errEmail}</span>}
      </div>
      <div className="space-devider"></div>

      <div className="flexrow">
        <input
          type="text"
          name="Username"
          className="login-input"
          placeholder="User name"
          value={username}
          onChange={(e) => usernameChange(e.target.value)}
        />
        {errUser && <span className="error-style">{errUser}</span>}
      </div>
      <div className="space-devider"></div>

      {/* password */}
      <div className="flexrow password-container">
      <div className="input-wrapper">
        <input
          type={showPassword ? "text" : "password"}
          name="Password"
          className="login-input"
          placeholder="Password"
          onChange={(e) => passwordChange(e.target.value)}
        />
        {hasPasswordInput && (
          <span
          className="eye-icon"
          onClick={togglePasswordVisibility}
        >
            <SVGIcons
              icon={showPassword ? "eye-slash" : "eye"}
              fill="#d9d9d9"
            />
          </span>
        )}
        </div>
        {errPass && <span className="error-style">{errPass}</span>}
      </div>

      <div className="space-devider"></div>

      {/* confirm password */}
      <div className="flexrow password-container">
        <div className="input-wrapper">
        <input
          type={showConfirmPassword ? "text" : "password"}
          name="ConfirmPassword"
          className="login-input"
          placeholder="Confirm Password"
          onChange={(e) => confirmPasswordChange(e.target.value)}
        />
        {hasPasswordInput && hasConfirmPasswordInput && (
          <span
          className="eye-icon"
          onClick={toggleConfirmPasswordVisibility}
        >
            <SVGIcons
              icon={showConfirmPassword ? "eye-slash" : "eye"}
              fill="#d9d9d9"
            />
          </span>
        )}
        </div>
        {errConfirmPass && (
          <span className="error-style">{errConfirmPass}</span>
        )}
      </div>

      <div className="space-devider"></div>

      <div className="dropdown">
        <button className="dropdown-toggle" onClick={toggleDropdown}>
          {selectedOption}
          <div className="downbox">
            <SVGIcons icon="downarrow" width={20} height={18} fill="#000000" />
          </div>
          {/* <IoIosArrowDropdownCircle className="arrow-icon" style={{opacity:1}} size={20}/> */}
        </button>
        {isOpen && (
          <ul className="dropdown-menu">
            {roleOptions.map((option) => (
              <li key={option} onClick={() => handleOptionSelect(option)}>
                {option}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="space-devider"></div>

      <div>
        {msgSubmit && (
          <span
            className={
              msgSubmitApproval === true ? "success-style" : "error-style"
            }
          >
            {msgSubmit}
          </span>
        )}
      </div>
      <div className="submit-style">
        <div className="remember-style">
          <input type="checkbox" name="Remember me" className="checkbox" />
          <span style={{ fontSize: 12, marginLeft: 8, bottom: 5 }}>
            Remember me{" "}
          </span>
        </div>
        <div className="div-hyperstyle">
          <a href="/login" className="hyperlink">
            Login
          </a>
          <button
            type="button"
            className="button-style"
            onClick={(e) => onSubmit(e)}
            icon
          >
            <h2 className="signIntext"> Sign Up </h2>
            <div className="signarrow">
              <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
            </div>

            {/* Sign In <FaCircleChevronRight size={15} className="chevron-right" color={"#0071B3"}/> */}
          </button>
        </div>
      </div>
    </div>
  );
};

export default SignUp;
