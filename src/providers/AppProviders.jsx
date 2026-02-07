/**
 * Centralized Application Providers
 *
 * This file ensures all context providers are wrapped in the correct order
 * to prevent "undefined" errors when components try to use contexts.
 *
 * Provider Order (from outer to inner):
 * 1. MessageProvider - Used by all other providers for notifications
 * 2. ErrorBoundary - Catches all errors (can now use MessageContext)
 * 3. AuthProvider - Authentication state (depends on MessageProvider)
 * 4. VersionProvider - App version info
 * 5. ApiUrlProvider - API configuration
 * 6. GlobalComponentProvider - Global UI components
 */

import { MessageProvider } from "../Hooks/MessageContext";
import { AuthProvider } from "../context/AuthContext";
import { VersionProvider } from "../context/VersionContext";
import { ApiUrlProvider } from "../context/ApiUrlContext";
import { GlobalComponentProvider } from "../Hooks/GlobalComponentContext";
import { ErrorBoundaryWrapper } from "../components/errorhandling/ErrorBoundary";

export const AppProviders = ({ children }) => {
  return (
    <MessageProvider>
      <ErrorBoundaryWrapper>
        <AuthProvider>
          <VersionProvider>
            <ApiUrlProvider>
              <GlobalComponentProvider>{children}</GlobalComponentProvider>
            </ApiUrlProvider>
          </VersionProvider>
        </AuthProvider>
      </ErrorBoundaryWrapper>
    </MessageProvider>
  );
};

export default AppProviders;
