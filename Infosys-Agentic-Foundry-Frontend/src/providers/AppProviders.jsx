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
 * 4. PermissionsProvider - Role-based permissions (depends on AuthProvider)
 * 5. VersionProvider - App version info
 * 6. ApiUrlProvider - API configuration
 * 7. GlobalComponentProvider - Global UI components
 */

import { MessageProvider } from "../Hooks/MessageContext";
import { AuthProvider } from "../context/AuthContext";
import { PermissionsProvider } from "../context/PermissionsContext";
import { VersionProvider } from "../context/VersionContext";
import { ApiUrlProvider } from "../context/ApiUrlContext";
import { GlobalComponentProvider } from "../Hooks/GlobalComponentContext";
import { ErrorBoundaryWrapper } from "../components/errorhandling/ErrorBoundary";
import { ThemeProvider } from "../Hooks/ThemeContext";

export const AppProviders = ({ children }) => {
  return (
    <ThemeProvider>
      <MessageProvider>
        <ErrorBoundaryWrapper>
          <AuthProvider>
            <PermissionsProvider>
              <VersionProvider>
                <ApiUrlProvider>
                  <GlobalComponentProvider>{children}</GlobalComponentProvider>
                </ApiUrlProvider>
              </VersionProvider>
            </PermissionsProvider>
          </AuthProvider>
        </ErrorBoundaryWrapper>
      </MessageProvider>
    </ThemeProvider>
  );
};

export default AppProviders;
