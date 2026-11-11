import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";

import { clearTokens } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { AuthPage } from "./AuthPage";

function renderAuth(mode: "login" | "register") {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[`/${mode}`]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<AuthPage mode="login" />} />
            <Route path="/register" element={<AuthPage mode="register" />} />
            <Route path="/" element={<p>Dashboard home</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AuthPage", () => {
  beforeEach(() => clearTokens());

  it("signs in and leaves the login page (BR-01)", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ access_token: "a", refresh_token: "r", expires_in: 900 }), { status: 200 }),
    );
    renderAuth("login");

    await userEvent.type(screen.getByLabelText("Email"), "sara@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "correct-horse-battery-staple");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Dashboard home")).toBeInTheDocument();
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toEqual({
      email: "sara@example.com",
      password: "correct-horse-battery-staple",
    });
  });

  it("shows the API's message when sign-in fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ title: "Unauthorized", status: 401, detail: "Incorrect email or password." }), {
        status: 401,
      }),
    );
    renderAuth("login");

    await userEvent.type(screen.getByLabelText("Email"), "sara@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password-1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password.");
  });

  it("explains the password rule when registering", () => {
    renderAuth("register");

    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription("At least 12 characters.");
    expect(screen.getByLabelText("Password")).toHaveAttribute("minLength", "12");
  });
});
