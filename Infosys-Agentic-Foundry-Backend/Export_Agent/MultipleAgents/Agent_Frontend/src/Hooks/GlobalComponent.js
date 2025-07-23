import { React, useEffect } from "react";
import { useGlobalComponent } from "./GlobalComponentContext";
import "./GlobalComponent.css";
import MessageUpdateform from "../components/AskAssistant/MsgUpdateform";

const GlobalComponent = () => {
  const { isVisible, hideComponent } = useGlobalComponent();

  useEffect(() => {
    if (isVisible) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "auto";
    }
    return () => {
      document.body.style.overflow = "auto";
    };
  }, [isVisible]);

  if (!isVisible) return null;

  return (
    <MessageUpdateform isVisible={isVisible} hideComponent={hideComponent} />
  );
};

export default GlobalComponent;
