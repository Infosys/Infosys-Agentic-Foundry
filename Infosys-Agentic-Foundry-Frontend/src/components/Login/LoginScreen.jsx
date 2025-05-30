import React, { useState,useRef } from "react";
import "./login.css";
import { useNavigate } from "react-router-dom";
import SVGIcons from "../../Icons/SVGIcons";
import useFetch from "../../Hooks/useAxios";
import Cookies from "js-cookie";
import { roleOptions } from "../../constant";

// import { IoIosArrowDropdownCircle } from "react-icons/io";
// import { FaCircleChevronRight } from "react-icons/fa6";

function LoginScreen() {
  const { postData, fetchData, setCsrfToken } = useFetch();

  // const [username, setUsername] = useState("");
  // const [errUser, setErrUser] = useState("");
  const [email, setEmail] = useState("");
  const [errEmail, setErrEmail] = useState("");
  // Use a ref instead to avoid storing in state
  const passwordRef = useRef("");
  // Add this state variable with your other state declarations
  const [hasPasswordInput, setHasPasswordInput] = useState(false);


  const [errPass, setErrPass] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [items, setItems] = useState("");
  const [errSubmit, setErrSubmit] = useState(false);
  const [msgSubmit, setMsgSubmit] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  const navigate = useNavigate();

  const [isOpen, setIsOpen] = useState(false);
  const [selectedOption, setSelectedOption] = useState("Select Role");

  const togglePasswordVisibility = () => {
    setShowPassword((prev) => !prev);
  };

  const toggleDropdown = () => {
    setIsOpen(!isOpen);
  };

  const handleOptionSelect = (option) => {
    setSelectedOption(option);
    setIsOpen(false);
  };

  const emailChange = (value) => {
    const emailRegex = /^[a-zA-Z0-9+_.-]+@[a-zA-Z0-9.-]+$/;
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
  };

  const passwordChange = (value) => {
    const passwordRegex =
      /^(?=.*[a-zA-Z])(?=.*\d)(?=.*[!@#$%^&*()_+~`|}{[\]:;?><,./])/;
    
    // Store the password in the ref instead of state to overcome vulnerability
    passwordRef.current = value;

    // Update state to track if password field has content
    setHasPasswordInput(value.length > 0);
  
    
    if (value) {
      if (value?.length < 6) {
        setErrPass("Password must be atleast 6 characters long");
      } else if (!passwordRegex.test(value)) {
        setErrPass(
          "Password must have 1 letter,1 number and 1 special character"
        );
      } else {
        setErrPass("");
      }
    } else {
      setErrPass("");
    }
  };

  const clearError = () => {
    setTimeout(() => {
      setMsgSubmit("");
    }, 3000);
  };

  const onSubmit = async () => {
    try {
      if (email === "" || passwordRef.current === "" || selectedOption === "Select Role") {
        setErrSubmit(true);
        setMsgSubmit("Please fill up all the fields");
        clearError();
      } else if (errEmail || errPass) {
        setErrSubmit(true);
        setMsgSubmit("Please enter proper value in input field");
        clearError();
      } else {
        const users = await postData("/login", {
          email_id: email,
          password: passwordRef.current,
          role: selectedOption,
        });

        // Store CSRF token from response if it exists
        if (users?.csrf_token) {
          setCsrfToken(users.csrf_token);
        }

        if (users.approval) {
          Cookies.set("userName", users.username);
          Cookies.set("session_id", users.session_id);
          Cookies.set("email", users.email);
          Cookies.set("role", users.role);
          navigate("/");
          setMsgSubmit("Success");
          clearError();
          setErrSubmit(false);
        } else {
          setErrSubmit(true);
          setMsgSubmit(users.message);
          clearError();
        }

        // Clear the password from memory after use
        passwordRef.current = "";
      }
    } catch (error) {
      // Clear the password from memory after use
      passwordRef.current = "";
      setErrSubmit(true);
      setMsgSubmit("An error occurred. Please try again.");
      clearError();
      console.log("Error:", error);
    }
  };

  const handleGuestLogin = async (e) => {
    e.preventDefault();
    try {
      const users = await fetchData("/login_guest");
      if (users.approval) {
        Cookies.set("userName", users.user_name);
        Cookies.set("session_id", users.session_id);
        Cookies.set("email", users.email);
        navigate("/");
        setMsgSubmit(users.message);
        clearError();
        setErrSubmit(false);
      } else {
        setErrSubmit(true);
        setMsgSubmit("Guest Login Failed");
        clearError();
      }
    } catch (error) {
      setErrSubmit(true);
      setMsgSubmit("An error occurred. Please try again.");
      clearError();
    }
  };

  return (
    <div className="login-container">
      <h3 className="title">Sign In</h3>

      {/* email */}
      <div className="flexrow">
        <input
          type="text"
          name="Email"
          className="loginPage-input"
          placeholder="Email"
          value={email}
          onChange={(e) => emailChange(e.target.value)}
        />
        {errEmail && <span className="error-style">{errEmail}</span>}
      </div>

      <div className="space-devider"></div>

      {/* password */}
      <div className="flexrow password-container">
      <div className="input-wrapper">
        <input
          type={showPassword ? "text" : "password"}
          name="Password"
          className="loginPage-input"
          placeholder="Password"
          autoComplete="current-password"
          onChange={(e) => passwordChange(e.target.value)}
        /> {/*  Removed the value prop value={password} modified to ref to overcome vulnerability issue */}
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
              msgSubmit === "Success" ? "success-style" : "error-style"
            }
          >
            {msgSubmit}
          </span>
        )}
      </div>
      <div className="submit-style">
        {/* <div className="remember-style">
          <input type="checkbox" name="Remember me" className="checkbox" />
          <span style={{ fontSize: 12, marginLeft: 8, bottom: 5 }}>
            Remember me{" "}
          </span>
        </div> */}

        {/* login as guest button */}
        <button
          type="button"
          className="button-style"
          onClick={(e) => handleGuestLogin(e)}
        >
          <h2 className="signIntext"> Login as Guest </h2>
          <div className="signarrow">
            <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
          </div>
        </button>

        <div className="div-hyperstyle">
          {/* <a href="/register" className="hyperlink">
            Register
          </a> */}
          <button
            type="button"
            className="button-style"
            onClick={() => onSubmit()}
            icon
          >
            <h2 className="signIntext"> Sign In </h2>
            <div className="signarrow">
              <SVGIcons icon="rightarrow" width={20} height={18} fill="#fff" />
            </div>

            {/* Sign In <FaCircleChevronRight size={15} className="chevron-right" color={"#0071B3"}/> */}
          </button>
        </div>
      </div>
    </div>
  );
}

export default LoginScreen;
