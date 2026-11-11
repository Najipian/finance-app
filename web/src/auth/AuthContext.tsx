import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react";

import {
  api,
  clearTokens,
  hasSession,
  refreshToken,
  setSessionEndedHandler,
  storeTokens,
  type TokenPair,
} from "../api/client";
import { AuthContext } from "./context";

export interface AuthState {
  signedIn: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}


export function AuthProvider({ children }: { children: ReactNode }) {
  const [signedIn, setSignedIn] = useState(hasSession);
  const queryClient = useQueryClient();

  const endSession = useCallback(() => {
    clearTokens();
    queryClient.clear();
    setSignedIn(false);
  }, [queryClient]);

  useEffect(() => setSessionEndedHandler(endSession), [endSession]);

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api<TokenPair>("/auth/login", {
      method: "POST",
      body: { email, password },
      auth: false,
    });
    storeTokens(tokens);
    setSignedIn(true);
  }, []);

  const register = useCallback(
    async (email: string, password: string) => {
      await api("/auth/register", { method: "POST", body: { email, password }, auth: false });
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    const token = refreshToken();
    if (token) {
      await api("/auth/logout", { method: "POST", body: { refresh_token: token }, auth: false }).catch(
        () => undefined,
      );
    }
    endSession();
  }, [endSession]);

  const value = useMemo(() => ({ signedIn, login, register, logout }), [signedIn, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
