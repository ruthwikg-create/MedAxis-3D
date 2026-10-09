import { create } from "zustand";

type Workspace =
  | "2D Research Viewer"
  | "4-Panel MPR"
  | "3D Reconstruction"
  | "AI Analysis"
  | "Quantitative Analysis"
  | "Comparison"
  | "Reporting"
  | "Full Workstation";
type Mode = "BASIC" | "ADVANCED" | "RADIOLOGY" | "RESEARCH" | "ENGINEERING";
type Plane = "axial" | "sagittal" | "coronal";

type Position = { z: number; y: number; x: number };

type State = {
  workspace: Workspace;
  mode: Mode;
  panelLeft: boolean;
  panelRight: boolean;
  panelBottom: boolean;
  plane: Plane;
  position: Position;
  windowLevel: number | null;
  windowWidth: number | null;
  set: (patch: Partial<State>) => void;
  setSlice: (index: number) => void;
};

export const useAppStore = create<State>((set, get) => ({
  workspace: "2D Research Viewer",
  mode: "RADIOLOGY",
  panelLeft: true,
  panelRight: true,
  panelBottom: true,
  plane: "axial",
  position: { z: 0, y: 0, x: 0 },
  windowLevel: null,
  windowWidth: null,
  set: (patch) => set(patch),
  setSlice: (index) => {
    const { plane, position } = get();
    const safe = Math.max(0, Math.floor(index));
    if (plane === "axial") set({ position: { ...position, z: safe } });
    if (plane === "coronal") set({ position: { ...position, y: safe } });
    if (plane === "sagittal") set({ position: { ...position, x: safe } });
  },
}));
