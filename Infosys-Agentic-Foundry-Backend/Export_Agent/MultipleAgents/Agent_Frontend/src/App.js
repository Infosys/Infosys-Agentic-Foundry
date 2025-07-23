import "./App.css";
import AskAssistant from "./components/AskAssistant/AskAssistant";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { MessageProvider } from "./Hooks/MessageContext";
import MessagePopup from "./components/MessagePopup/MessagePopup";
import { GlobalComponentProvider } from "./Hooks/GlobalComponentContext";
import GlobalComponent from "./Hooks/GlobalComponent";

import { ApiUrlProvider } from "./context/ApiUrlContext";
import { VersionProvider } from "./context/VersionContext";


function App() {

  return (
    <>
      <BrowserRouter>
        <GlobalComponentProvider>
          <GlobalComponent />          <MessageProvider>
            <MessagePopup />
            <VersionProvider>
              <ApiUrlProvider>
                <Routes>           
              <Route
                path="/chat"
                element={
                    <Layout>
                      <AskAssistant />
                    </Layout>
                }
              />
              
              {/* default Route */}
              <Route path="*" element={<Navigate to="/chat" />} />
                          
              </Routes>
              </ApiUrlProvider>
            </VersionProvider>
          </MessageProvider>
        </GlobalComponentProvider>
      </BrowserRouter>
    </>
  );
}

export default App;
