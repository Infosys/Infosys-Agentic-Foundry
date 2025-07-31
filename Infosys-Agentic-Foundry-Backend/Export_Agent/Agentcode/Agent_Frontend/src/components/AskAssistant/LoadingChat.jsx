import React, { useEffect, useState } from "react";

const LoadingChat = (props) => {
  const { label = "Generating" } = props;
  const [dots, setDots] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setDots((prevDots) => (prevDots + 1) % 5);
    }, 300);

    return () => clearInterval(interval);
  }, []);
  return <>{label + ".".repeat(dots)}</>;
};

export default LoadingChat;
