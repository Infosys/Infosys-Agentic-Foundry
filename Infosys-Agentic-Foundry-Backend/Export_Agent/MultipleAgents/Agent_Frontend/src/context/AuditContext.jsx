import React, { createContext, useContext, useState } from "react";

const AuditContext = createContext();

export const AuditProvider = ({ children }) => {
  const [auditData, setAuditData] = useState(null);

  return (
    <AuditContext.Provider value={{ auditData, setAuditData }}>
      {children}
    </AuditContext.Provider>
  );
};

export const useAuditContext = () => {
  const context = useContext(AuditContext);
  if (!context) {
    throw new Error("useAuditContext must be used within an AuditProvider");
  }
  return context;
};