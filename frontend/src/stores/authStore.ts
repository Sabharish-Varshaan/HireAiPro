import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Role =
  | "STUDENT"
  | "COMPANY_ADMIN"
  | "RECRUITER"
  | "HIRING_MANAGER"
  | "INSTITUTION_ADMIN"
  | "PLACEMENT_OFFICER"
  | "FACULTY"
  | "DEPARTMENT_HEAD"
  | "PLATFORM_ADMIN";

interface AuthState {
  token: string | null;
  userId: string | null;
  role: Role | null;
  fullName: string | null;
  setAuth: (token: string, userId: string, role: Role, fullName: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      userId: null,
      role: null,
      fullName: null,
      setAuth: (token, userId, role, fullName) => set({ token, userId, role, fullName }),
      logout: () => set({ token: null, userId: null, role: null, fullName: null }),
    }),
    { name: "hireai-auth" }
  )
);
